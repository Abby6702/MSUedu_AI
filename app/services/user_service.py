"""All database work for users and profiles lives here, so route files stay short."""
import pymysql
from werkzeug.security import generate_password_hash
from app.db import get_connection, query_all, query_one, execute


class EmailAlreadyUsed(Exception):
    pass


# ---------- reading ----------
def get_user_by_id(user_id):
    return query_one(
        "SELECT id, full_name, email, role, is_active, must_change_password, session_version "
        "FROM users WHERE id = %s",
        (user_id,),
    )


def get_user_for_login(email):
    return query_one(
        "SELECT id, full_name, email, password_hash, role, is_active, session_version "
        "FROM users WHERE email = %s",
        (email,),
    )


def get_password_hash(user_id):
    row = query_one("SELECT password_hash FROM users WHERE id = %s", (user_id,))
    return row["password_hash"] if row else None


def get_profile(user_id, role):
    if role == "student":
        return query_one(
            "SELECT course, year_level, learning_goals FROM student_profiles WHERE user_id = %s",
            (user_id,),
        )
    if role == "tutor":
        return query_one(
            "SELECT student_number, course, year_level, bio, approval_status "
            "FROM tutor_profiles WHERE user_id = %s",
            (user_id,),
        )
    return None


# ---------- writing ----------
def create_user(full_name, email, password, role):
    """Create the user AND their empty profile in one transaction:
    either both are saved or neither is."""
    password_hash = generate_password_hash(password)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (full_name, email, password_hash, role) "
                "VALUES (%s, %s, %s, %s)",
                (full_name, email, password_hash, role),
            )
            user_id = cur.lastrowid
            if role == "student":
                cur.execute("INSERT INTO student_profiles (user_id) VALUES (%s)", (user_id,))
            elif role == "tutor":
                cur.execute("INSERT INTO tutor_profiles (user_id) VALUES (%s)", (user_id,))
        conn.commit()
        return user_id
    except pymysql.err.IntegrityError as error:
        conn.rollback()
        if error.args and error.args[0] == 1062:   # duplicate email
            raise EmailAlreadyUsed() from error
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_password(user_id, new_password):
    """Save a new password, clear the 'must change' flag and bump session_version, which
    logs out every other session of this user. Returns the NEW session_version."""
    hashed = generate_password_hash(new_password)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s, must_change_password = 0, "
                "session_version = session_version + 1 WHERE id = %s",
                (hashed, user_id))
            cur.execute("SELECT session_version FROM users WHERE id = %s", (user_id,))
            version = cur.fetchone()["session_version"]
        conn.commit()
        return version
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_profile(user_id, role, data):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET full_name = %s WHERE id = %s",
                        (data["full_name"], user_id))
            if role == "student":
                cur.execute(
                    "UPDATE student_profiles SET course=%s, year_level=%s, learning_goals=%s "
                    "WHERE user_id=%s",
                    (data["course"], data["year_level"], data["learning_goals"] or None, user_id),
                )
            elif role == "tutor":
                cur.execute(
                    "UPDATE tutor_profiles SET student_number=%s, course=%s, year_level=%s, bio=%s "
                    "WHERE user_id=%s",
                    (data["student_number"] or None, data["course"], data["year_level"],
                     data["bio"] or None, user_id),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_login(user_id):
    execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (user_id,))


def log_audit(actor_user_id, action, target_type=None, target_id=None, details=None):
    """Never put passwords or private messages in `details`."""
    execute(
        "INSERT INTO audit_logs (actor_user_id, action, target_type, target_id, details) "
        "VALUES (%s, %s, %s, %s, %s)",
        (actor_user_id, action, target_type, target_id, details),
    )


# ---------- admin dashboard numbers ----------
def count_users_by_role():
    counts = {"student": 0, "tutor": 0, "admin": 0}
    for row in query_all("SELECT role, COUNT(*) AS n FROM users GROUP BY role"):
        counts[row["role"]] = row["n"]
    return counts


def count_pending_tutors():
    row = query_one("SELECT COUNT(*) AS n FROM tutor_profiles WHERE approval_status = 'pending'")
    return row["n"]