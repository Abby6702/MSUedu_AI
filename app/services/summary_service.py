"""Database work for structured session summaries, and the lesson lists the tutor tools use.
Every query that returns a session includes the tutor's or the student's own user id."""
from app.db import execute, query_all, query_one
from app.timeutil import utcnow

_SESSION = (
    "SELECT r.id, r.student_id, r.tutor_id, r.subject_id, r.topic, r.status, r.start_at, r.end_at, "
    "s.name AS subject_name, su.full_name AS student_name, tu.full_name AS tutor_name "
    "FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
    "JOIN users su ON su.id = r.student_id JOIN users tu ON tu.id = r.tutor_id WHERE r.id = %s AND ")


def get_session_for_tutor(request_id, tutor_id):
    """The booking, only if this user is its tutor."""
    return query_one(_SESSION + "r.tutor_id = %s", (request_id, tutor_id))


def lessons_for_subject(subject_id):
    return query_all(
        "SELECT l.id, l.title, t.name AS topic_name FROM lessons l "
        "JOIN topics t ON t.id = l.topic_id AND t.is_active = 1 "
        "WHERE t.subject_id = %s AND l.is_active = 1 ORDER BY t.level, t.position, l.id", (subject_id,))


def record_topics(request_id):
    """The topics from the tutor's quick session record (Phase 8), used to pre-fill the summary."""
    row = query_one("SELECT topics_covered FROM session_records WHERE request_id = %s", (request_id,))
    return row["topics_covered"] if row else ""


def get_summary(request_id):
    return query_one("SELECT topics_covered, strengths, improvements, practice, next_lesson_id, status, "
                     "ai_assisted FROM session_summaries WHERE request_id = %s", (request_id,))


def save_summary(request_id, tutor_id, data, approve):
    """Save (or update) the summary. approve=True shares it with the student."""
    now = utcnow()
    execute(
        "INSERT INTO session_summaries (request_id, tutor_id, topics_covered, strengths, improvements, "
        "practice, next_lesson_id, status, ai_assisted, created_at, updated_at, approved_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE topics_covered = VALUES(topics_covered), strengths = VALUES(strengths), "
        "improvements = VALUES(improvements), practice = VALUES(practice), "
        "next_lesson_id = VALUES(next_lesson_id), status = VALUES(status), "
        "ai_assisted = VALUES(ai_assisted), updated_at = VALUES(updated_at), approved_at = VALUES(approved_at)",
        (request_id, tutor_id, data["topics_covered"], data["strengths"] or None,
         data["improvements"] or None, data["practice"] or None, data["next_lesson_id"],
         "approved" if approve else "draft", 1 if data["ai_assisted"] else 0,
         now, now, now if approve else None))


def get_approved_for_student(request_id, student_id):
    """A shared summary, only for the student of that booking. Drafts are never returned."""
    return query_one(
        "SELECT ss.request_id, ss.topics_covered, ss.strengths, ss.improvements, ss.practice, "
        "ss.ai_assisted, ss.approved_at, r.start_at, r.end_at, s.name AS subject_name, "
        "tu.full_name AS tutor_name, l.id AS lesson_id, l.title AS lesson_title "
        "FROM session_summaries ss JOIN tutoring_requests r ON r.id = ss.request_id "
        "JOIN subjects s ON s.id = r.subject_id JOIN users tu ON tu.id = r.tutor_id "
        "LEFT JOIN lessons l ON l.id = ss.next_lesson_id AND l.is_active = 1 "
        "WHERE ss.request_id = %s AND r.student_id = %s AND ss.status = 'approved'",
        (request_id, student_id))


def student_summaries(student_id, limit=5):
    return query_all(
        "SELECT ss.request_id, ss.improvements, ss.approved_at, s.name AS subject_name, "
        "tu.full_name AS tutor_name, l.id AS lesson_id, l.title AS lesson_title "
        "FROM session_summaries ss JOIN tutoring_requests r ON r.id = ss.request_id "
        "JOIN subjects s ON s.id = r.subject_id JOIN users tu ON tu.id = r.tutor_id "
        "LEFT JOIN lessons l ON l.id = ss.next_lesson_id AND l.is_active = 1 "
        "WHERE r.student_id = %s AND ss.status = 'approved' ORDER BY ss.approved_at DESC LIMIT %s",
        (student_id, limit))