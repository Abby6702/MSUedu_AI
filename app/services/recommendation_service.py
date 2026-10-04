"""Runs the learning agent for a student and stores what it decided."""
import json

from flask import current_app

from app.db import get_connection, query_all
from app.services import learning_agent, notification_service, profile_service
from app.timeutil import utcnow

LESSON_ROWS_SQL = (
    "SELECT t.id AS topic_id, t.subject_id, t.name AS topic_name, s.name AS subject_name, "
    "l.id AS lesson_id, l.title, (lp.lesson_id IS NOT NULL) AS completed "
    "FROM topics t JOIN subjects s ON s.id = t.subject_id AND s.is_active = 1 "
    "JOIN lessons l ON l.topic_id = t.id AND l.is_active = 1 "
    "LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id AND lp.user_id = %s "
    "WHERE t.is_active = 1 ORDER BY t.subject_id, t.level, t.position, l.id")


def compute(user_id):
    """Collect data -> analyze -> decide. Reads only stored events, never chat content."""
    topics = profile_service.summarize_topics(profile_service.topic_attempt_rows(user_id))
    by_topic, by_subject = learning_agent.index_lessons(query_all(LESSON_ROWS_SQL, (user_id,)))
    return learning_agent.decide_all(topics, by_topic, by_subject)


def sync(user_id, desired):
    """Apply the plan in ONE transaction. Returns [(new_id, rec)] for inserted recommendations."""
    conn = get_connection()
    inserted = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, kind, status, evidence, dedupe_key FROM recommendations "
                        "WHERE user_id = %s AND dedupe_key IS NOT NULL FOR UPDATE", (user_id,))
            existing = {r["dedupe_key"]: r for r in cur.fetchall()}
            plan = learning_agent.plan_sync(existing, desired)
            now = utcnow()
            for rec_id, status in plan["retire"]:
                cur.execute("UPDATE recommendations SET status = %s, dedupe_key = NULL, resolved_at = %s "
                            "WHERE id = %s AND user_id = %s", (status, now, rec_id, user_id))
            for rec_id, d in plan["update"]:
                cur.execute("UPDATE recommendations SET title = %s, message = %s, reasoning = %s, "
                            "evidence = %s, lesson_id = %s, difficulty = %s WHERE id = %s AND user_id = %s",
                            (d["title"], d["message"], json.dumps(d["reasoning"]), d["evidence"],
                             d["lesson_id"], d["difficulty"], rec_id, user_id))
            for d in plan["insert"]:
                cur.execute(
                    "INSERT INTO recommendations (user_id, topic_id, subject_id, lesson_id, kind, "
                    "difficulty, title, message, reasoning, evidence, status, dedupe_key, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)",
                    (user_id, d["topic_id"], d["subject_id"], d["lesson_id"], d["kind"], d["difficulty"],
                     d["title"], d["message"], json.dumps(d["reasoning"]), d["evidence"], d["key"], now))
                inserted.append((cur.lastrowid, d))
        conn.commit()
        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def notify_new(user_id, inserted):
    """Tell the student about NEW review or tutor recommendations. Never breaks the main action."""
    for rec_id, d in inserted:
        if d["kind"] == "next_lesson":
            continue
        try:
            notification_service.notify(user_id, "recommendation", d["title"], d["message"],
                                        "/student/learning/recommendations", f"rec:{rec_id}")
        except Exception:
            current_app.logger.exception("Could not create a recommendation notification")


def run_agent(user_id):
    desired = compute(user_id)
    notify_new(user_id, sync(user_id, desired))
    return desired


def safe_run(user_id):
    """Run the agent after an activity. A failure is logged and never blocks the student's action.
    Skipped in automated tests, so route tests never touch a real database."""
    if current_app.config.get("TESTING"):
        return []
    try:
        return run_agent(user_id)
    except Exception:
        current_app.logger.exception("The learning agent failed")
        return []


# ---------- reading ----------
def _load(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {"steps": []}


def list_active(user_id, limit=50):
    rows = query_all(
        "SELECT id, kind, difficulty, title, message, reasoning, topic_id, subject_id, lesson_id, created_at "
        "FROM recommendations WHERE user_id = %s AND status = 'active' "
        "ORDER BY FIELD(kind, 'human_tutor', 'review_lesson', 'practice', 'next_lesson'), created_at DESC "
        "LIMIT %s", (user_id, limit))
    for row in rows:
        row["reasoning"] = _load(row["reasoning"])
    return rows


def top_active(user_id, limit=3):
    return list_active(user_id, limit)


def dismiss(rec_id, user_id):
    """The key stays, so the same advice does not come straight back. True if something changed."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            changed = cur.execute("UPDATE recommendations SET status = 'dismissed', resolved_at = %s "
                                  "WHERE id = %s AND user_id = %s AND status = 'active'",
                                  (utcnow(), rec_id, user_id))
        conn.commit()
        return changed == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()