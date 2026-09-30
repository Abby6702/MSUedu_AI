"""Database work for feedback, session records and learning progress."""
import pymysql
from app.db import execute, query_all, query_one
from app.timeutil import utcnow


class FeedbackExists(Exception):
    pass


_COMPLETED = (
    "SELECT r.id, r.student_id, r.tutor_id, r.topic, r.start_at, r.end_at, "
    "s.name AS subject_name, su.full_name AS student_name, tu.full_name AS tutor_name "
    "FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
    "JOIN users su ON su.id = r.student_id JOIN users tu ON tu.id = r.tutor_id "
    "WHERE r.id = %s AND r.status = 'completed' AND "
)


def get_completed_for_student(request_id, student_id):
    """A completed session, only if it belongs to this student."""
    return query_one(_COMPLETED + "r.student_id = %s", (request_id, student_id))


def get_completed_for_tutor(request_id, tutor_id):
    """A completed session, only if it belongs to this tutor."""
    return query_one(_COMPLETED + "r.tutor_id = %s", (request_id, tutor_id))


# ---------- feedback ----------
def get_feedback(request_id):
    return query_one("SELECT rating, comment, created_at FROM feedback WHERE request_id = %s",
                     (request_id,))


def create_feedback(request_id, student_id, tutor_id, rating, comment):
    try:
        return execute(
            "INSERT INTO feedback (request_id, student_id, tutor_id, rating, comment, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (request_id, student_id, tutor_id, rating, comment or None, utcnow()),
        )
    except pymysql.err.IntegrityError as error:
        if error.args and error.args[0] == 1062:     # already sent for this session
            raise FeedbackExists() from error
        raise


def tutor_feedback(tutor_id, limit=50):
    """Visible feedback about a tutor. No student names are selected on purpose."""
    return query_all(
        "SELECT f.rating, f.comment, f.created_at, s.name AS subject_name "
        "FROM feedback f JOIN tutoring_requests r ON r.id = f.request_id "
        "JOIN subjects s ON s.id = r.subject_id "
        "WHERE f.tutor_id = %s AND f.is_hidden = 0 "
        "ORDER BY f.created_at DESC, f.id DESC LIMIT %s",
        (tutor_id, limit),
    )


def rating_summary(tutor_id):
    """{'n': how many ratings, 'avg': average or None}. Hidden feedback is not counted."""
    row = query_one("SELECT COUNT(*) AS n, AVG(rating) AS avg FROM feedback "
                    "WHERE tutor_id = %s AND is_hidden = 0", (tutor_id,))
    n = row["n"] if row else 0
    return {"n": n, "avg": round(float(row["avg"]), 1) if n and row["avg"] is not None else None}


# ---------- session records ----------
def get_record(request_id):
    return query_one(
        "SELECT topics_covered, outcomes, next_steps, summary_text, summary_ai_assisted, updated_at "
        "FROM session_records WHERE request_id = %s", (request_id,))


def save_record(request_id, tutor_id, data):
    execute(
        "INSERT INTO session_records (request_id, tutor_id, topics_covered, outcomes, next_steps, "
        "summary_text, summary_ai_assisted, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE topics_covered = VALUES(topics_covered), "
        "outcomes = VALUES(outcomes), next_steps = VALUES(next_steps), "
        "summary_text = VALUES(summary_text), summary_ai_assisted = VALUES(summary_ai_assisted), "
        "updated_at = VALUES(updated_at)",
        (request_id, tutor_id, data["topics_covered"], data["outcomes"],
         data["next_steps"] or None, data["summary_text"] or None,
         1 if data["ai_assisted"] else 0, utcnow()),
    )


# ---------- a student's own progress ----------
def student_completed_sessions(student_id, limit=30):
    return query_all(
        "SELECT r.id, r.start_at, r.end_at, s.name AS subject_name, tu.full_name AS tutor_name, "
        "sr.topics_covered, sr.outcomes, sr.next_steps, sr.summary_text, sr.summary_ai_assisted, "
        "f.rating "
        "FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
        "JOIN users tu ON tu.id = r.tutor_id "
        "LEFT JOIN session_records sr ON sr.request_id = r.id "
        "LEFT JOIN feedback f ON f.request_id = r.id "
        "WHERE r.student_id = %s AND r.status = 'completed' "
        "ORDER BY r.start_at DESC LIMIT %s",
        (student_id, limit),
    )


def activity_counts(user_id):
    """How often the student used each AI feature. Counts only, never content."""
    counts = {}
    for row in query_all("SELECT feature, COUNT(*) AS n FROM ai_usage_logs "
                         "WHERE user_id = %s AND success = 1 GROUP BY feature", (user_id,)):
        counts[row["feature"]] = row["n"]
    return counts