"""Database work for the curriculum (topics and lessons) that administrators manage.
Topics and lessons are hidden (is_active = 0), so progress, quiz links and recommendations
that point at them stay valid."""
import pymysql

from app.db import execute, query_all, query_one


class TopicExists(Exception):
    pass


class LessonExists(Exception):
    pass


def _duplicate(error):
    return bool(error.args) and error.args[0] == 1062


# ---------- rules (no database, easy to test) ----------
def build_tree(rows):
    """Flat rows (ordered by level, position, lesson) -> levels > topics > lessons."""
    levels, by_level, by_topic = [], {}, {}
    for r in rows:
        level = by_level.get(r["level"])
        if level is None:
            level = {"level": r["level"], "topics": []}
            by_level[r["level"]] = level
            levels.append(level)
        topic = by_topic.get(r["topic_id"])
        if topic is None:
            topic = {"id": r["topic_id"], "name": r["topic_name"], "position": r["position"],
                     "active": bool(r["topic_active"]), "lessons": []}
            by_topic[r["topic_id"]] = topic
            level["topics"].append(topic)
        if r["lesson_id"] is not None:
            topic["lessons"].append({"id": r["lesson_id"], "title": r["title"], "difficulty": r["difficulty"],
                                     "minutes": r["minutes"], "active": bool(r["lesson_active"])})
    return levels


# ---------- subjects and the tree ----------
def list_subjects():
    return query_all(
        "SELECT s.id, s.name, s.category, s.is_active, "
        "(SELECT COUNT(*) FROM topics t WHERE t.subject_id = s.id) AS topics, "
        "(SELECT COUNT(*) FROM lessons l JOIN topics t ON t.id = l.topic_id "
        " WHERE t.subject_id = s.id AND t.is_active = 1 AND l.is_active = 1) AS lessons "
        "FROM subjects s ORDER BY s.name")


def get_subject(subject_id):
    return query_one("SELECT id, name, category, is_active FROM subjects WHERE id = %s", (subject_id,))


def subject_tree(subject_id):
    return build_tree(query_all(
        "SELECT t.id AS topic_id, t.name AS topic_name, t.level, t.position, t.is_active AS topic_active, "
        "l.id AS lesson_id, l.title, l.difficulty, l.minutes, l.is_active AS lesson_active "
        "FROM topics t LEFT JOIN lessons l ON l.topic_id = t.id WHERE t.subject_id = %s "
        "ORDER BY t.level, t.position, t.id, l.id", (subject_id,)))


# ---------- topics ----------
def get_topic(topic_id):
    return query_one(
        "SELECT t.id, t.subject_id, t.name, t.level, t.position, t.is_active, s.name AS subject_name "
        "FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE t.id = %s", (topic_id,))


def next_position(subject_id, level):
    row = query_one("SELECT COALESCE(MAX(position), 0) + 1 AS n FROM topics "
                    "WHERE subject_id = %s AND level = %s", (subject_id, level))
    return min(int(row["n"]), 99)


def create_topic(subject_id, data):
    position = data["position"] or next_position(subject_id, data["level"])
    try:
        return execute("INSERT INTO topics (subject_id, name, level, position) VALUES (%s, %s, %s, %s)",
                       (subject_id, data["name"], data["level"], position))
    except pymysql.err.IntegrityError as error:
        if _duplicate(error):
            raise TopicExists() from error
        raise


def update_topic(topic_id, data):
    try:
        execute("UPDATE topics SET name = %s, level = %s, position = %s WHERE id = %s",
                (data["name"], data["level"], data["position"], topic_id))
    except pymysql.err.IntegrityError as error:
        if _duplicate(error):
            raise TopicExists() from error
        raise


def set_topic_active(topic_id, active):
    execute("UPDATE topics SET is_active = %s WHERE id = %s", (1 if active else 0, topic_id))


# ---------- lessons ----------
def get_lesson(lesson_id):
    return query_one(
        "SELECT l.id, l.topic_id, l.title, l.body, l.difficulty, l.minutes, l.is_active, "
        "t.name AS topic_name, t.subject_id, s.name AS subject_name "
        "FROM lessons l JOIN topics t ON t.id = l.topic_id JOIN subjects s ON s.id = t.subject_id "
        "WHERE l.id = %s", (lesson_id,))


def create_lesson(topic_id, data):
    try:
        return execute("INSERT INTO lessons (topic_id, title, body, difficulty, minutes) "
                       "VALUES (%s, %s, %s, %s, %s)",
                       (topic_id, data["title"], data["body"], data["difficulty"], data["minutes"]))
    except pymysql.err.IntegrityError as error:
        if _duplicate(error):
            raise LessonExists() from error
        raise


def update_lesson(lesson_id, data):
    try:
        execute("UPDATE lessons SET title = %s, body = %s, difficulty = %s, minutes = %s WHERE id = %s",
                (data["title"], data["body"], data["difficulty"], data["minutes"], lesson_id))
    except pymysql.err.IntegrityError as error:
        if _duplicate(error):
            raise LessonExists() from error
        raise


def set_lesson_active(lesson_id, active):
    execute("UPDATE lessons SET is_active = %s WHERE id = %s", (1 if active else 0, lesson_id))