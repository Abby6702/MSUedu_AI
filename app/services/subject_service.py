"""Database work for the subject list."""
import pymysql
from app.db import execute, query_all, query_one


class SubjectExists(Exception):
    pass


def list_subjects(active_only=True):
    sql = "SELECT id, name, category, is_active FROM subjects"
    if active_only:
        sql += " WHERE is_active = 1"
    return query_all(sql + " ORDER BY category, name")


def create_subject(name, category):
    try:
        return execute("INSERT INTO subjects (name, category) VALUES (%s, %s)",
                       (name, category or None))
    except pymysql.err.IntegrityError as error:
        if error.args and error.args[0] == 1062:
            raise SubjectExists() from error
        raise


def toggle_subject(subject_id):
    """Flip active/inactive. Returns the new state, or None if not found."""
    row = query_one("SELECT is_active FROM subjects WHERE id = %s", (subject_id,))
    if row is None:
        return None
    new_state = 0 if row["is_active"] else 1
    execute("UPDATE subjects SET is_active = %s WHERE id = %s", (new_state, subject_id))
    return new_state


def count_active_subjects():
    return query_one("SELECT COUNT(*) AS n FROM subjects WHERE is_active = 1")["n"]