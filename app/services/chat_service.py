"""Saved AI tutor conversations. Every query that touches a conversation includes the
owner's user_id, so nobody can read or change someone else's chats."""
from app.db import execute, get_connection, query_all, query_one
from app.services import ai_service
from app.timeutil import utcnow

DEFAULT_TITLE = "New conversation"
MAX_CONVERSATIONS = 50
MAX_MESSAGES = 200
TITLE_LENGTH = 60


# ---------- rules (no database, easy to test) ----------
def make_title(text):
    text = " ".join((text or "").split())
    if not text:
        return DEFAULT_TITLE
    return text if len(text) <= TITLE_LENGTH else text[:TITLE_LENGTH - 1].rstrip() + "\u2026"


def build_messages(system, history, user_text=None):
    """system prompt + cleaned stored history (+ the new question). A 'system' role in the
    history is dropped, so stored or forged data can never change the tutor's rules."""
    messages = [{"role": "system", "content": system}]
    messages += ai_service.clean_history(history)
    if user_text is not None:
        messages.append({"role": "user", "content": user_text})
    return messages


# ---------- conversations ----------
def count_conversations(user_id):
    return query_one("SELECT COUNT(*) AS n FROM ai_conversations WHERE user_id = %s", (user_id,))["n"]


def create_conversation(user_id, subject_id, lesson_id):
    now = utcnow()
    return execute(
        "INSERT INTO ai_conversations (user_id, title, subject_id, lesson_id, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)", (user_id, DEFAULT_TITLE, subject_id, lesson_id, now, now))


def list_conversations(user_id, limit=MAX_CONVERSATIONS):
    return query_all(
        "SELECT c.id, c.title, c.updated_at, s.name AS subject_name, l.title AS lesson_title "
        "FROM ai_conversations c LEFT JOIN subjects s ON s.id = c.subject_id "
        "LEFT JOIN lessons l ON l.id = c.lesson_id WHERE c.user_id = %s "
        "ORDER BY c.updated_at DESC, c.id DESC LIMIT %s", (user_id, limit))


def get_conversation(conversation_id, user_id):
    """The conversation, only if it belongs to this student."""
    return query_one(
        "SELECT c.id, c.title, c.subject_id, c.lesson_id, s.name AS subject_name, l.title AS lesson_title "
        "FROM ai_conversations c LEFT JOIN subjects s ON s.id = c.subject_id "
        "LEFT JOIN lessons l ON l.id = c.lesson_id WHERE c.id = %s AND c.user_id = %s",
        (conversation_id, user_id))


def delete_conversation(conversation_id, user_id):
    execute("DELETE FROM ai_conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))


# ---------- messages (call get_conversation first, so ownership is already checked) ----------
def all_messages(conversation_id):
    return query_all("SELECT id, role, content FROM ai_messages WHERE conversation_id = %s ORDER BY id",
                     (conversation_id,))


def recent_messages(conversation_id, limit):
    rows = query_all("SELECT id, role, content FROM ai_messages WHERE conversation_id = %s "
                     "ORDER BY id DESC LIMIT %s", (conversation_id, limit))
    return list(reversed(rows))


def count_messages(conversation_id):
    return query_one("SELECT COUNT(*) AS n FROM ai_messages WHERE conversation_id = %s",
                     (conversation_id,))["n"]


def add_exchange(conversation_id, user_text, reply):
    """Save the question AND its answer together, or neither."""
    now = utcnow()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for role, content in (("user", user_text), ("assistant", reply)):
                cur.execute("INSERT INTO ai_messages (conversation_id, role, content, created_at) "
                            "VALUES (%s, %s, %s, %s)", (conversation_id, role, content, now))
            cur.execute("UPDATE ai_conversations SET updated_at = %s, "
                        "title = IF(title = %s, %s, title) WHERE id = %s",
                        (now, DEFAULT_TITLE, make_title(user_text), conversation_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def replace_reply(conversation_id, message_id, reply):
    """Regenerate: swap the text of the last assistant message."""
    now = utcnow()
    execute("UPDATE ai_messages SET content = %s, created_at = %s "
            "WHERE id = %s AND conversation_id = %s AND role = 'assistant'",
            (reply, now, message_id, conversation_id))
    execute("UPDATE ai_conversations SET updated_at = %s WHERE id = %s", (now, conversation_id))


def clear_messages(conversation_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE m FROM ai_messages m JOIN ai_conversations c ON c.id = m.conversation_id "
                        "WHERE c.id = %s AND c.user_id = %s", (conversation_id, user_id))
            cur.execute("UPDATE ai_conversations SET title = %s, updated_at = %s "
                        "WHERE id = %s AND user_id = %s",
                        (DEFAULT_TITLE, utcnow(), conversation_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()