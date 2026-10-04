"""Saved chat messages of live sessions. Callers check that the user belongs to the booking first."""
from app.db import execute, query_all, query_one
from app.timeutil import utcnow

MAX_MESSAGES = 500


def count(request_id):
    return query_one("SELECT COUNT(*) AS n FROM session_messages WHERE request_id = %s",
                     (request_id,))["n"]


def add_message(request_id, user_id, body):
    return execute("INSERT INTO session_messages (request_id, user_id, body, created_at) "
                   "VALUES (%s, %s, %s, %s)", (request_id, user_id, body, utcnow()))


def recent(request_id, limit=100):
    """The latest messages, oldest first."""
    rows = query_all(
        "SELECT m.id, u.full_name AS name, m.body, m.created_at, "
        "CASE WHEN m.user_id = r.tutor_id THEN 'tutor' ELSE 'student' END AS role "
        "FROM session_messages m JOIN users u ON u.id = m.user_id "
        "JOIN tutoring_requests r ON r.id = m.request_id "
        "WHERE m.request_id = %s ORDER BY m.id DESC LIMIT %s", (request_id, limit))
    return list(reversed(rows))