"""Lessons, learning paths and lesson progress. Progress is stored as events
(completed lessons), never guessed from AI chat."""
from datetime import timedelta

from app.db import get_connection, query_all, query_one
from app.timeutil import to_local, utcnow


# ---------- rules (no database, easy to test) ----------
def percent(done, total):
    return round(100 * done / total) if total else 0


def compute_streak(days, today):
    """days: a set of dates (Philippine time) on which the student completed a lesson.
    The streak is the run of consecutive days ending today, or ending yesterday if
    nothing has been completed today yet (so it does not reset before the day is over)."""
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def build_path(rows):
    """Group flat lesson rows (ordered by level, position, lesson) into levels > topics > lessons."""
    levels, by_level, by_topic, next_lesson, done = [], {}, {}, None, 0
    for r in rows:
        level = by_level.get(r["level"])
        if level is None:
            level = {"level": r["level"], "topics": [], "done": 0, "total": 0}
            by_level[r["level"]] = level
            levels.append(level)
        topic = by_topic.get(r["topic_id"])
        if topic is None:
            topic = {"id": r["topic_id"], "name": r["topic_name"], "lessons": [], "done": 0, "total": 0}
            by_topic[r["topic_id"]] = topic
            level["topics"].append(topic)
        completed = bool(r["completed"])
        topic["lessons"].append({"id": r["lesson_id"], "title": r["title"], "difficulty": r["difficulty"],
                                 "minutes": r["minutes"], "completed": completed})
        for box in (topic, level):
            box["total"] += 1
            box["done"] += completed
        done += completed
        if not completed and next_lesson is None:
            next_lesson = {"id": r["lesson_id"], "title": r["title"], "topic": r["topic_name"]}
    total = sum(level["total"] for level in levels)
    return {"levels": levels, "done": done, "total": total,
            "percent": percent(done, total), "next": next_lesson}


# ---------- reading ----------
def list_learning_subjects(user_id):
    rows = query_all(
        "SELECT s.id, s.name, s.category, COUNT(l.id) AS total, COUNT(lp.lesson_id) AS done "
        "FROM subjects s JOIN topics t ON t.subject_id = s.id AND t.is_active = 1 "
        "JOIN lessons l ON l.topic_id = t.id AND l.is_active = 1 "
        "LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id AND lp.user_id = %s "
        "WHERE s.is_active = 1 GROUP BY s.id, s.name, s.category ORDER BY s.name",
        (user_id,))
    for row in rows:
        row["percent"] = percent(row["done"], row["total"])
    return rows


def get_subject(subject_id):
    return query_one("SELECT id, name, category FROM subjects WHERE id = %s AND is_active = 1",
                     (subject_id,))


def path_rows(user_id, subject_id):
    return query_all(
        "SELECT t.id AS topic_id, t.name AS topic_name, t.level, t.position, "
        "l.id AS lesson_id, l.title, l.difficulty, l.minutes, "
        "(lp.lesson_id IS NOT NULL) AS completed "
        "FROM topics t JOIN lessons l ON l.topic_id = t.id AND l.is_active = 1 "
        "LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id AND lp.user_id = %s "
        "WHERE t.subject_id = %s AND t.is_active = 1 ORDER BY t.level, t.position, l.id",
        (user_id, subject_id))


def get_lesson(lesson_id, user_id):
    return query_one(
        "SELECT l.id, l.title, l.body, l.difficulty, l.minutes, t.id AS topic_id, "
        "t.name AS topic_name, t.level, s.id AS subject_id, s.name AS subject_name, "
        "(SELECT COUNT(*) FROM lesson_progress lp WHERE lp.lesson_id = l.id AND lp.user_id = %s) AS completed "
        "FROM lessons l JOIN topics t ON t.id = l.topic_id JOIN subjects s ON s.id = t.subject_id "
        "WHERE l.id = %s AND l.is_active = 1 AND t.is_active = 1 AND s.is_active = 1",
        (user_id, lesson_id))


def overall_stats(user_id):
    rows = query_all("SELECT completed_at FROM lesson_progress WHERE user_id = %s", (user_id,))
    days = {to_local(r["completed_at"]).date() for r in rows}
    return {"completed": len(rows),
            "streak": compute_streak(days, to_local(utcnow()).date())}


# ---------- writing ----------
def mark_complete(user_id, lesson_id):
    """True if this is a NEW completion, False if it was already completed."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            added = cur.execute(
                "INSERT IGNORE INTO lesson_progress (user_id, lesson_id, completed_at) VALUES (%s, %s, %s)",
                (user_id, lesson_id, utcnow()))
        conn.commit()
        return added == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

        

def list_topics():
    """Active topics with their subject, for the quiz form."""
    return query_all(
        "SELECT t.id, t.subject_id, t.name, t.level, s.name AS subject_name "
        "FROM topics t JOIN subjects s ON s.id = t.subject_id "
        "WHERE t.is_active = 1 AND s.is_active = 1 ORDER BY s.name, t.level, t.position")



def list_lessons_for_select():
    """Active lessons with their subject, for the AI tutor's context list."""
    return query_all(
        "SELECT l.id, l.title, s.id AS subject_id, s.name AS subject_name "
        "FROM lessons l JOIN topics t ON t.id = l.topic_id AND t.is_active = 1 "
        "JOIN subjects s ON s.id = t.subject_id AND s.is_active = 1 "
        "WHERE l.is_active = 1 ORDER BY s.name, t.level, t.position, l.id")