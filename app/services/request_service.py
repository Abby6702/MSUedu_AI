"""All database work and rules for tutoring requests and sessions."""
from datetime import timedelta
from flask import current_app
from app.db import get_connection, query_all, query_one
from app.services import notification_service
from app.timeutil import to_local, utcnow

MAX_OPEN_REQUESTS = 5
OPEN_STATUSES = ("pending", "reschedule_proposed")

# (current status, action) -> (who may do it, new status).
# "either" means the student or the tutor of that request.
TRANSITIONS = {
    ("pending", "accept"): ("tutor", "accepted"),
    ("pending", "decline"): ("tutor", "declined"),
    ("pending", "propose"): ("tutor", "reschedule_proposed"),
    ("pending", "cancel"): ("student", "cancelled"),
    ("reschedule_proposed", "accept_proposal"): ("student", "accepted"),
    ("reschedule_proposed", "cancel"): ("either", "cancelled"),
    ("accepted", "cancel"): ("either", "cancelled"),
    ("accepted", "complete"): ("tutor", "completed"),
}

MESSAGES = {
    "accept": "Session confirmed.",
    "accept_proposal": "New time accepted. The session is confirmed.",
    "decline": "Request declined.",
    "cancel": "Cancelled.",
    "complete": "Session marked as completed.",
}

# Which notification event each action creates.
EVENT_BY_ACTION = {
    "accept": "accepted",
    "accept_proposal": "proposal_accepted",
    "decline": "declined",
    "cancel": "cancelled",
    "complete": "completed",
}

LIST_SQL = """
SELECT r.id, r.student_id, r.tutor_id, r.topic, r.description, r.session_format,
       r.start_at, r.end_at, r.status, r.proposed_start_at, r.proposed_end_at,
       r.response_note, s.name AS subject_name,
       su.full_name AS student_name, tu.full_name AS tutor_name,
       (SELECT COUNT(*) FROM feedback f WHERE f.request_id = r.id) AS has_feedback,
       (SELECT COUNT(*) FROM session_records sr WHERE sr.request_id = r.id) AS has_record
FROM tutoring_requests r
JOIN subjects s ON s.id = r.subject_id
JOIN users su ON su.id = r.student_id
JOIN users tu ON tu.id = r.tutor_id
"""


def _notify(event, request_id, actor_id):
    """A notification problem must never break a booking: log it and carry on."""
    try:
        notification_service.request_event(request_id, event, actor_id)
    except Exception:
        current_app.logger.exception("Could not create a notification")


# ---------- rules (no database) ----------
def next_status(status, action, role):
    """New status if this role may do this action now, otherwise None."""
    rule = TRANSITIONS.get((status, action))
    if rule is None:
        return None
    who, new_status = rule
    return new_status if who in (role, "either") else None


def available_actions(req, role):
    actions = []
    for (status, action) in TRANSITIONS:
        if status != req["status"] or next_status(status, action, role) is None:
            continue
        if action == "complete" and req["end_at"] > utcnow():
            continue        # a session can only be completed after it ends
        actions.append(action)
    return actions


# ---------- reading ----------
def tutor_subject_options(tutor_id):
    return query_all(
        "SELECT s.id, s.name FROM tutor_subjects ts JOIN subjects s ON s.id = ts.subject_id "
        "WHERE ts.tutor_id = %s AND s.is_active = 1 ORDER BY s.name",
        (tutor_id,),
    )


def get_for_user(request_id, user_id):
    """Returns the request only if this user is its student or its tutor."""
    return query_one(
        LIST_SQL + " WHERE r.id = %s AND (r.student_id = %s OR r.tutor_id = %s)",
        (request_id, user_id, user_id),
    )


def grouped_requests(user_id, role):
    rows = query_all(
        LIST_SQL + " WHERE r.student_id = %s OR r.tutor_id = %s ORDER BY r.start_at",
        (user_id, user_id),
    )
    attention, upcoming, history = [], [], []
    for row in rows:
        row["actions"] = available_actions(row, role)
        if row["status"] in OPEN_STATUSES:
            attention.append(row)
        elif row["status"] == "accepted":
            upcoming.append(row)
        else:
            history.append(row)
    history.reverse()       # newest first
    return {"attention": attention, "upcoming": upcoming, "history": history}


# ---------- locking and checks (used inside transactions) ----------
def _lock_users(cur, user_a, user_b):
    """Lock both users' rows, always in id order (prevents deadlocks). Anyone else
    trying to book or accept for the same people must wait for us to finish."""
    ids = sorted({user_a, user_b})
    marks = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT id FROM users WHERE id IN ({marks}) ORDER BY id FOR UPDATE", ids)


def _overlapping_accepted(cur, column, user_id, start, end, exclude_id=0):
    """Is there another ACCEPTED session for this user that overlaps [start, end)?
    Two ranges overlap when each starts before the other ends."""
    if column not in ("tutor_id", "student_id"):
        raise ValueError("column must be tutor_id or student_id")
    cur.execute(
        f"SELECT id FROM tutoring_requests WHERE {column} = %s AND status = 'accepted' "
        "AND id <> %s AND start_at < %s AND end_at > %s LIMIT 1 FOR UPDATE",
        (user_id, exclude_id, end, start),
    )
    return cur.fetchone() is not None


def _fits_availability(cur, tutor_id, start_utc, end_utc):
    """Is the whole session inside one of the tutor's weekly slots (Philippine time)?"""
    s, e = to_local(start_utc), to_local(end_utc)
    if s.date() != e.date():
        return False
    s_time = timedelta(hours=s.hour, minutes=s.minute)
    e_time = timedelta(hours=e.hour, minutes=e.minute)
    cur.execute(
        "SELECT id FROM tutor_availability WHERE tutor_id = %s AND day_of_week = %s "
        "AND start_time <= %s AND end_time >= %s LIMIT 1",
        (tutor_id, s.weekday(), s_time, e_time),     # weekday(): Monday = 0
    )
    return cur.fetchone() is not None


def _check_can_confirm(cur, req, start, end):
    """Returns a problem message, or None if the session can be confirmed."""
    if start is None or start <= utcnow():
        return "That time has already passed."
    _lock_users(cur, req["student_id"], req["tutor_id"])
    if _overlapping_accepted(cur, "tutor_id", req["tutor_id"], start, end, req["id"]):
        return "The tutor already has a confirmed session at that time."
    if _overlapping_accepted(cur, "student_id", req["student_id"], start, end, req["id"]):
        return "The student already has a confirmed session at that time."
    return None


# ---------- writing ----------
def create_request(student_id, tutor_id, data, dry_run=False):
    """Returns (new_id, problem). With dry_run=True it runs every check but saves nothing."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _lock_users(cur, student_id, tutor_id)
            cur.execute(
                "SELECT tp.tutoring_format FROM users u "
                "JOIN tutor_profiles tp ON tp.user_id = u.id "
                "JOIN tutor_subjects ts ON ts.tutor_id = u.id "
                "JOIN subjects s ON s.id = ts.subject_id "
                "WHERE u.id = %s AND u.role = 'tutor' AND u.is_active = 1 "
                "AND tp.approval_status = 'approved' AND ts.subject_id = %s AND s.is_active = 1",
                (tutor_id, data["subject_id"]),
            )
            tutor = cur.fetchone()
            if tutor is None:
                return None, "This tutor does not teach that subject or cannot receive requests right now."
            if tutor["tutoring_format"] not in ("both", data["format"]):
                return None, "This tutor does not offer that format."
            if not _fits_availability(cur, tutor_id, data["start"], data["end"]):
                return None, "That time is outside the tutor's listed weekly availability."
            if _overlapping_accepted(cur, "tutor_id", tutor_id, data["start"], data["end"]):
                return None, "The tutor already has a confirmed session at that time. Choose another time."
            if _overlapping_accepted(cur, "student_id", student_id, data["start"], data["end"]):
                return None, "You already have a confirmed session at that time."

            cur.execute(
                "SELECT id FROM tutoring_requests WHERE student_id = %s AND tutor_id = %s "
                "AND subject_id = %s AND start_at = %s "
                "AND status IN ('pending','reschedule_proposed','accepted') LIMIT 1 FOR UPDATE",
                (student_id, tutor_id, data["subject_id"], data["start"]),
            )
            if cur.fetchone():
                return None, "You already have a request for this tutor, subject and time."
            cur.execute(
                "SELECT COUNT(*) AS n FROM tutoring_requests WHERE student_id = %s "
                "AND status IN ('pending','reschedule_proposed')",
                (student_id,),
            )
            if cur.fetchone()["n"] >= MAX_OPEN_REQUESTS:
                return None, f"You can have at most {MAX_OPEN_REQUESTS} open requests. Wait for replies or cancel one."

            if dry_run:
                return None, None
            cur.execute(
                "INSERT INTO tutoring_requests (student_id, tutor_id, subject_id, topic, "
                "description, session_format, start_at, end_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (student_id, tutor_id, data["subject_id"], data["topic"],
                 data["description"] or None, data["format"], data["start"], data["end"]),
            )
            new_id = cur.lastrowid
        conn.commit()
        _notify("created", new_id, student_id)
        return new_id, None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def perform_action(request_id, actor_id, action, note=None):
    """Runs one action from TRANSITIONS. Returns (ok, message)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tutoring_requests WHERE id = %s FOR UPDATE", (request_id,))
            req = cur.fetchone()
            if req is None or actor_id not in (req["student_id"], req["tutor_id"]):
                return False, "Request not found."
            role = "tutor" if actor_id == req["tutor_id"] else "student"
            new_status = next_status(req["status"], action, role)
            if new_status is None:
                return False, "That action is not possible for this request right now."

            if action in ("accept", "accept_proposal"):
                if action == "accept":
                    start, end = req["start_at"], req["end_at"]
                else:
                    start, end = req["proposed_start_at"], req["proposed_end_at"]
                problem = _check_can_confirm(cur, req, start, end)
                if problem:
                    return False, problem
                cur.execute(
                    "UPDATE tutoring_requests SET status = 'accepted', start_at = %s, end_at = %s, "
                    "proposed_start_at = NULL, proposed_end_at = NULL WHERE id = %s",
                    (start, end, request_id),
                )
            elif action == "complete":
                if req["end_at"] > utcnow():
                    return False, "You can mark a session completed only after it ends."
                cur.execute("UPDATE tutoring_requests SET status = 'completed' WHERE id = %s",
                            (request_id,))
            else:   # decline or cancel
                cur.execute(
                    "UPDATE tutoring_requests SET status = %s, "
                    "response_note = COALESCE(%s, response_note) WHERE id = %s",
                    (new_status, note or None, request_id),
                )
        conn.commit()
        _notify(EVENT_BY_ACTION[action], request_id, actor_id)
        return True, MESSAGES[action]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def propose_time(request_id, tutor_id, start, end, note):
    """Tutor suggests another time for a pending request. Returns (ok, message)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tutoring_requests WHERE id = %s FOR UPDATE", (request_id,))
            req = cur.fetchone()
            if req is None or req["tutor_id"] != tutor_id:
                return False, "Request not found."
            if next_status(req["status"], "propose", "tutor") is None:
                return False, "You can only propose a new time for a pending request."
            if start <= utcnow():
                return False, "That time has already passed."
            _lock_users(cur, req["student_id"], tutor_id)
            if not _fits_availability(cur, tutor_id, start, end):
                return False, "That time is outside your weekly availability."
            if _overlapping_accepted(cur, "tutor_id", tutor_id, start, end, req["id"]):
                return False, "You already have a confirmed session at that time."
            cur.execute(
                "UPDATE tutoring_requests SET status = 'reschedule_proposed', "
                "proposed_start_at = %s, proposed_end_at = %s, response_note = %s WHERE id = %s",
                (start, end, note or None, request_id),
            )
        conn.commit()
        _notify("proposed", request_id, tutor_id)
        return True, "New time proposed. The student must accept it before anything is confirmed."
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()