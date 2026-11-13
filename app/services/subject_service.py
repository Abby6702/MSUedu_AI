"""Database work for the subject list."""
import pymysql
from app.db import execute, get_connection, query_all, query_one


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


def create_tutor_subject_request(tutor_id, data):
    """Save a tutor's proposed subject for administrator review."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM subjects WHERE name = %s LIMIT 1 FOR UPDATE",
                        (data["name"],))
            if cur.fetchone():
                conn.rollback()
                raise SubjectExists()
            cur.execute(
                "SELECT id FROM tutor_subject_requests WHERE tutor_id = %s AND subject_name = %s "
                "AND status = 'pending' LIMIT 1 FOR UPDATE",
                (tutor_id, data["name"]),
            )
            if cur.fetchone():
                conn.rollback()
                raise SubjectExists()
            cur.execute(
                "INSERT INTO tutor_subject_requests "
                "(tutor_id, subject_name, category, topics, rate_30, rate_60, rate_90, rate_120) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (tutor_id, data["name"], data["category"] or None, data["topics"] or None,
                 data["rates"][30], data["rates"][60], data["rates"][90], data["rates"][120]),
            )
            request_id = cur.lastrowid
        conn.commit()
        return request_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def tutor_subject_requests(tutor_id):
    return query_all(
        "SELECT id, subject_name, category, status, created_at FROM tutor_subject_requests "
        "WHERE tutor_id = %s ORDER BY created_at DESC, id DESC",
        (tutor_id,),
    )


def list_subject_requests(status=None):
    sql = (
        "SELECT r.id, r.tutor_id, r.subject_name, r.category, r.topics, r.rate_30, r.rate_60, "
        "r.rate_90, r.rate_120, r.status, r.created_at, u.full_name AS tutor_name "
        "FROM tutor_subject_requests r JOIN users u ON u.id = r.tutor_id"
    )
    params = ()
    if status:
        sql += " WHERE r.status = %s"
        params = (status,)
    return query_all(sql + " ORDER BY r.created_at, r.id", params)


def review_subject_request(request_id, admin_id, decision):
    """Approve a proposal into the catalog and assign it to its requesting tutor, or reject it."""
    if decision not in ("approved", "rejected"):
        raise ValueError("Unsupported subject-request decision.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tutor_subject_requests WHERE id = %s FOR UPDATE",
                        (request_id,))
            proposal = cur.fetchone()
            if proposal is None or proposal["status"] != "pending":
                conn.rollback()
                return False
            if decision == "approved":
                cur.execute("SELECT id, is_active FROM subjects WHERE name = %s FOR UPDATE",
                            (proposal["subject_name"],))
                subject = cur.fetchone()
                if subject:
                    subject_id = subject["id"]
                    if not subject["is_active"]:
                        cur.execute("UPDATE subjects SET is_active = 1 WHERE id = %s", (subject_id,))
                else:
                    cur.execute("INSERT INTO subjects (name, category) VALUES (%s, %s)",
                                (proposal["subject_name"], proposal["category"]))
                    subject_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO tutor_subjects "
                    "(tutor_id, subject_id, topics, rate_30, rate_60, rate_90, rate_120) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE topics = VALUES(topics), rate_30 = VALUES(rate_30), "
                    "rate_60 = VALUES(rate_60), rate_90 = VALUES(rate_90), rate_120 = VALUES(rate_120)",
                    (proposal["tutor_id"], subject_id, proposal["topics"], proposal["rate_30"],
                     proposal["rate_60"], proposal["rate_90"], proposal["rate_120"]),
                )
            cur.execute(
                "UPDATE tutor_subject_requests SET status = %s, reviewed_by = %s, "
                "reviewed_at = CURRENT_TIMESTAMP WHERE id = %s AND status = 'pending'",
                (decision, admin_id, request_id),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()