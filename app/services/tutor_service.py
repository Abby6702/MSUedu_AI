"""Database work and matching rules for tutors."""
from datetime import datetime
from app.db import get_connection, query_all, query_one, execute
from app.validators_tutor import DAY_NAMES

MAX_SLOTS = 40
FORMAT_LABELS = {"online": "Online", "in_person": "In person", "both": "Online or in person"}

# Only these fixed strings can ever go after ORDER BY (never user text).
SORTS = {
    "name": "u.full_name ASC",
    "newest": "u.created_at DESC",
    "slots": "slot_count DESC, u.full_name ASC",
}

SEARCH_BASE = """
SELECT u.id, u.full_name, tp.course, tp.year_level, tp.tutoring_format,
  (SELECT GROUP_CONCAT(s.name ORDER BY s.name SEPARATOR ', ')
     FROM tutor_subjects ts JOIN subjects s ON s.id = ts.subject_id
    WHERE ts.tutor_id = u.id AND s.is_active = 1) AS subject_names,
  (SELECT COUNT(*) FROM tutor_availability ta WHERE ta.tutor_id = u.id) AS slot_count
FROM users u JOIN tutor_profiles tp ON tp.user_id = u.id
"""


# ---------- small helpers ----------
def fmt_time(value):
    """MySQL TIME (a timedelta) -> '2:00 PM'."""
    return (datetime.min + value).time().strftime("%I:%M %p").lstrip("0")


def fmt_range(start, end):
    return f"{fmt_time(start)} to {fmt_time(end)}"


def like_pattern(text):
    """Make user text safe for LIKE: % and _ are treated as normal characters."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# ---------- tutor's own setup ----------
def get_format(tutor_id):
    row = query_one("SELECT tutoring_format FROM tutor_profiles WHERE user_id = %s", (tutor_id,))
    return row["tutoring_format"] if row else "both"


def get_tutor_subjects(tutor_id):
    return query_all(
        "SELECT ts.subject_id, s.name, ts.topics FROM tutor_subjects ts "
        "JOIN subjects s ON s.id = ts.subject_id WHERE ts.tutor_id = %s ORDER BY s.name",
        (tutor_id,),
    )


def save_teaching_setup(tutor_id, tutoring_format, selections):
    """Replace the tutor's subject list and format in ONE transaction."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE tutor_profiles SET tutoring_format = %s WHERE user_id = %s",
                        (tutoring_format, tutor_id))
            cur.execute("DELETE FROM tutor_subjects WHERE tutor_id = %s", (tutor_id,))
            for subject_id, topics in selections:
                cur.execute(
                    "INSERT INTO tutor_subjects (tutor_id, subject_id, topics) VALUES (%s, %s, %s)",
                    (tutor_id, subject_id, topics or None),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def setup_summary(tutor_id):
    return query_one(
        "SELECT (SELECT COUNT(*) FROM tutor_subjects WHERE tutor_id = %s) AS subjects, "
        "(SELECT COUNT(*) FROM tutor_availability WHERE tutor_id = %s) AS slots",
        (tutor_id, tutor_id),
    )


# ---------- availability ----------
def list_availability(tutor_id):
    rows = query_all(
        "SELECT id, day_of_week, start_time, end_time FROM tutor_availability "
        "WHERE tutor_id = %s ORDER BY day_of_week, start_time",
        (tutor_id,),
    )
    for row in rows:
        row["day_name"] = DAY_NAMES[row["day_of_week"]]
        row["label"] = fmt_range(row["start_time"], row["end_time"])
    return rows


def add_slot(tutor_id, day, start, end):
    """Returns None on success, or a message explaining why it was refused."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM tutor_availability WHERE tutor_id = %s",
                        (tutor_id,))
            if cur.fetchone()["n"] >= MAX_SLOTS:
                return f"You can have at most {MAX_SLOTS} weekly slots."
            # Two ranges overlap when each one starts before the other ends.
            cur.execute(
                "SELECT id FROM tutor_availability WHERE tutor_id = %s AND day_of_week = %s "
                "AND start_time < %s AND end_time > %s LIMIT 1",
                (tutor_id, day, end, start),
            )
            if cur.fetchone():
                return "That time overlaps a slot you already added on the same day."
            cur.execute(
                "INSERT INTO tutor_availability (tutor_id, day_of_week, start_time, end_time) "
                "VALUES (%s, %s, %s, %s)",
                (tutor_id, day, start, end),
            )
        conn.commit()
        return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_slot(tutor_id, slot_id):
    """The tutor_id in WHERE means a tutor can only delete THEIR OWN slots."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            deleted = cur.execute(
                "DELETE FROM tutor_availability WHERE id = %s AND tutor_id = %s",
                (slot_id, tutor_id),
            )
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


# ---------- student search ----------
def build_search_query(f):
    """Builds SQL from fixed pieces. User text ONLY travels in `params`."""
    where = ["u.role = 'tutor'", "u.is_active = 1", "tp.approval_status = 'approved'"]
    params = []

    if f["q"]:
        like = like_pattern(f["q"])
        where.append(
            "(u.full_name LIKE %s OR EXISTS (SELECT 1 FROM tutor_subjects ts "
            "JOIN subjects s ON s.id = ts.subject_id WHERE ts.tutor_id = u.id "
            "AND s.is_active = 1 AND (s.name LIKE %s OR ts.topics LIKE %s)))"
        )
        params += [like, like, like]
    if f["subject_id"]:
        where.append(
            "EXISTS (SELECT 1 FROM tutor_subjects ts JOIN subjects s ON s.id = ts.subject_id "
            "WHERE ts.tutor_id = u.id AND ts.subject_id = %s AND s.is_active = 1)"
        )
        params.append(f["subject_id"])
    if f["course"]:
        where.append("tp.course LIKE %s")
        params.append(like_pattern(f["course"]))
    if f["day"] is not None:
        where.append("EXISTS (SELECT 1 FROM tutor_availability ta "
                     "WHERE ta.tutor_id = u.id AND ta.day_of_week = %s)")
        params.append(f["day"])
    if f["format"]:
        where.append("(tp.tutoring_format = %s OR tp.tutoring_format = 'both')")
        params.append(f["format"])

    sql = (SEARCH_BASE + " WHERE " + " AND ".join(where)
           + " ORDER BY " + SORTS[f["sort"]] + " LIMIT 50")
    return sql, params


def search_tutors(filters):
    sql, params = build_search_query(filters)
    return query_all(sql, params)


def get_public_tutor(tutor_id):
    """What students may see. Email and student number are NOT selected.
    Returns None unless the tutor is approved and active."""
    tutor = query_one(
        "SELECT u.id, u.full_name, tp.course, tp.year_level, tp.bio, tp.tutoring_format "
        "FROM users u JOIN tutor_profiles tp ON tp.user_id = u.id "
        "WHERE u.id = %s AND u.role = 'tutor' AND u.is_active = 1 "
        "AND tp.approval_status = 'approved'",
        (tutor_id,),
    )
    if tutor is None:
        return None
    tutor["subjects"] = query_all(
        "SELECT s.name, ts.topics FROM tutor_subjects ts JOIN subjects s ON s.id = ts.subject_id "
        "WHERE ts.tutor_id = %s AND s.is_active = 1 ORDER BY s.name",
        (tutor_id,),
    )
    tutor["availability"] = list_availability(tutor_id)
    return tutor


# ---------- matching ----------
def score_tutor(tutor, slots, criteria):
    """PURE function (no database), so it is easy to test.
    Returns None if the tutor must be excluded, otherwise
    {"score": int, "reasons": [...], "notes": [...]}.
    Every sentence is built only from stored data."""
    fmt, day, want = criteria["format"], criteria["day"], criteria["time"]

    if fmt and tutor["tutoring_format"] not in (fmt, "both"):
        return None    # hard filter: the format the student needs is not offered

    score, reasons, notes = 1, ["Teaches the subject you selected."], []
    if tutor.get("topics"):
        reasons.append(f"Lists these topics: {tutor['topics']}.")

    if fmt:
        score += 1
        reasons.append(f"Offers {FORMAT_LABELS[fmt].lower()} tutoring.")

    if day is not None:
        day_slots = [s for s in slots if s["day_of_week"] == day]
        if not day_slots:
            notes.append(f"No availability is listed on {DAY_NAMES[day]}.")
        else:
            score += 2
            ranges = ", ".join(fmt_range(s["start_time"], s["end_time"]) for s in day_slots)
            reasons.append(f"Has availability on {DAY_NAMES[day]}: {ranges}.")
            if want is not None:
                if any(s["start_time"] <= want < s["end_time"] for s in day_slots):
                    score += 1
                    reasons.append(f"Available at your preferred time ({fmt_time(want)}).")
                else:
                    notes.append(f"Not listed as available at {fmt_time(want)} on {DAY_NAMES[day]}.")
    return {"score": score, "reasons": reasons, "notes": notes}


def find_matches(subject_id, criteria):
    tutors = query_all(
        "SELECT u.id, u.full_name, tp.course, tp.year_level, tp.tutoring_format, ts.topics "
        "FROM tutor_subjects ts JOIN users u ON u.id = ts.tutor_id "
        "JOIN tutor_profiles tp ON tp.user_id = u.id "
        "JOIN subjects s ON s.id = ts.subject_id "
        "WHERE ts.subject_id = %s AND s.is_active = 1 AND u.role = 'tutor' "
        "AND u.is_active = 1 AND tp.approval_status = 'approved'",
        (subject_id,),
    )
    if not tutors:
        return []

    ids = [t["id"] for t in tutors]
    marks = ",".join(["%s"] * len(ids))   # only "%s,%s,..." is inserted; the ids stay parameters
    slot_rows = query_all(
        "SELECT tutor_id, day_of_week, start_time, end_time FROM tutor_availability "
        f"WHERE tutor_id IN ({marks})",
        ids,
    )

    results = []
    for tutor in tutors:
        own_slots = [s for s in slot_rows if s["tutor_id"] == tutor["id"]]
        scored = score_tutor(tutor, own_slots, criteria)
        if scored:
            results.append({"tutor": tutor, **scored})
    results.sort(key=lambda r: (-r["score"], r["tutor"]["full_name"]))
    return results


# ---------- admin review ----------
def list_tutors_for_review(status):
    return query_all(
        "SELECT u.id, u.full_name, u.email, tp.student_number, tp.course, tp.year_level, "
        "tp.bio, tp.tutoring_format, tp.approval_status, "
        "(SELECT GROUP_CONCAT(s.name ORDER BY s.name SEPARATOR ', ') FROM tutor_subjects ts "
        " JOIN subjects s ON s.id = ts.subject_id WHERE ts.tutor_id = u.id) AS subject_names "
        "FROM users u JOIN tutor_profiles tp ON tp.user_id = u.id "
        "WHERE tp.approval_status = %s ORDER BY u.created_at",
        (status,),
    )


def set_approval(tutor_id, new_status, admin_id):
    """Returns None on success or an error message."""
    tutor = query_one(
        "SELECT tp.course, tp.year_level, "
        "(SELECT COUNT(*) FROM tutor_subjects WHERE tutor_id = %s) AS subjects "
        "FROM tutor_profiles tp WHERE tp.user_id = %s",
        (tutor_id, tutor_id),
    )
    if tutor is None:
        return "Tutor not found."
    if new_status == "approved" and (
        not tutor["course"] or not tutor["year_level"] or tutor["subjects"] == 0
    ):
        return "Cannot approve: the tutor must have a course, year level and at least one subject."
    execute(
        "UPDATE tutor_profiles SET approval_status = %s, reviewed_by = %s, reviewed_at = NOW() "
        "WHERE user_id = %s",
        (new_status, admin_id, tutor_id),
    )
    return None