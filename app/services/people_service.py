"""Tutor profile details and photos, the tutor's 'My students' view, and the student's choice
to share a learning summary. Nothing here reads AI conversations, quiz answers or chat text."""
from app.db import execute, query_all, query_one
from app.services import learning_service, profile_service


# ---------- rules (no database, easy to test) ----------
def can_view_photo(role, viewer_id, tutor_id, approval_status, is_active):
    if role == "admin":
        return True
    if role == "tutor":
        return viewer_id == tutor_id                       # only your own photo
    if role == "student":
        return approval_status == "approved" and bool(is_active)
    return False


# ---------- tutor details and photo ----------
def get_details(tutor_id):
    return query_one("SELECT skills, education, experience, photo_filename FROM tutor_profiles "
                     "WHERE user_id = %s", (tutor_id,))


def save_details(tutor_id, data):
    execute("UPDATE tutor_profiles SET skills = %s, education = %s, experience = %s WHERE user_id = %s",
            (data["skills"] or None, data["education"] or None, data["experience"] or None, tutor_id))


def photo_info(tutor_id):
    return query_one("SELECT tp.photo_filename, tp.approval_status, u.is_active FROM tutor_profiles tp "
                     "JOIN users u ON u.id = tp.user_id WHERE tp.user_id = %s", (tutor_id,))


def set_photo(tutor_id, filename):
    execute("UPDATE tutor_profiles SET photo_filename = %s WHERE user_id = %s", (filename, tutor_id))


# ---------- My students (tutor) ----------
def list_students(tutor_id):
    rows = query_all(
        "SELECT r.student_id AS id, su.full_name, sp.course, sp.year_level, "
        "SUM(r.status = 'completed') AS completed, SUM(r.status = 'accepted') AS upcoming, "
        "MAX(CASE WHEN r.status = 'completed' THEN r.start_at END) AS last_session "
        "FROM tutoring_requests r JOIN users su ON su.id = r.student_id AND su.is_active = 1 "
        "LEFT JOIN student_profiles sp ON sp.user_id = su.id "
        "WHERE r.tutor_id = %s AND r.status IN ('accepted', 'completed') "
        "GROUP BY r.student_id, su.full_name, sp.course, sp.year_level "
        "ORDER BY upcoming DESC, last_session DESC, su.full_name", (tutor_id,))
    for row in rows:
        row["completed"], row["upcoming"] = int(row["completed"] or 0), int(row["upcoming"] or 0)
    return rows


def get_student(tutor_id, student_id):
    """The student, only if this tutor has a confirmed or completed session with them.
    Their learning goals are included only if they chose to share."""
    row = query_one(
        "SELECT su.id, su.full_name, sp.course, sp.year_level, sp.learning_goals, "
        "COALESCE(sp.share_progress_with_tutors, 0) AS shared "
        "FROM users su LEFT JOIN student_profiles sp ON sp.user_id = su.id "
        "WHERE su.id = %s AND su.role = 'student' AND su.is_active = 1 AND EXISTS ("
        "SELECT 1 FROM tutoring_requests r WHERE r.tutor_id = %s AND r.student_id = su.id "
        "AND r.status IN ('accepted', 'completed'))", (student_id, tutor_id))
    if row is None:
        return None
    row["shared"] = bool(row["shared"])
    if not row["shared"]:
        row["learning_goals"] = None
    return row


def student_sessions(tutor_id, student_id):
    return query_all(
        "SELECT r.id, r.status, r.start_at, r.end_at, r.topic, s.name AS subject_name, "
        "(SELECT COUNT(*) FROM session_records sr WHERE sr.request_id = r.id) AS has_record "
        "FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
        "WHERE r.tutor_id = %s AND r.student_id = %s AND r.status IN ('accepted', 'completed') "
        "ORDER BY r.start_at DESC LIMIT 30", (tutor_id, student_id))


def shared_summary(student_id):
    """Only called when the student opted in. Quiz averages per topic and lesson progress."""
    topics = profile_service.summarize_topics(profile_service.topic_attempt_rows(student_id))
    return {"needs_work": [t for t in topics if t["status"] == "weak"],
            "developing": [t for t in topics if t["status"] == "developing"],
            "strong": [t for t in topics if t["status"] == "strong"],
            "subjects": learning_service.list_learning_subjects(student_id)}


# ---------- the student's sharing choice ----------
def get_sharing(user_id):
    row = query_one("SELECT share_progress_with_tutors AS s FROM student_profiles WHERE user_id = %s",
                    (user_id,))
    return bool(row and row["s"])


def set_sharing(user_id, enabled):
    execute("UPDATE student_profiles SET share_progress_with_tutors = %s WHERE user_id = %s",
            (1 if enabled else 0, user_id))