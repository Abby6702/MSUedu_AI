"""MySQL helpers. Always pass values through `params` (never build SQL by
gluing strings together) so SQL injection is not possible."""
import pymysql
from pymysql.cursors import DictCursor
from flask import current_app


#def get_connection():
    # Read the combined service URI string directly
#    db_url = current_app.config["DATABASE_URL"]
    
    # This automatically handles the host, port, user, password, and SSL parameters securely!
#    return pymysql.from_url(db_url, cursorclass=DictCursor)

def get_connection():
    cfg = current_app.config
    return pymysql.connect(
        host=cfg["DB_HOST"],
        port=cfg["DB_PORT"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        database=cfg["DB_NAME"],
        charset="utf8mb4",
        cursorclass=DictCursor,   # rows come back as dictionaries
        connect_timeout=5,
        # Read and write TIMESTAMP columns in UTC, whatever the server's own time zone is.
        init_command="SET time_zone = '+00:00'",
        ssl={'ssl': True}
    )


def query_one(sql, params=None):
    """Run a SELECT and return one row (or None)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        conn.close()


def query_all(sql, params=None):
    """Run a SELECT and return a list of rows."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def execute(sql, params=None):
    """Run INSERT/UPDATE/DELETE, save it, and return the new row id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            new_id = cur.lastrowid
        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_database():
    """Return (True/False, message). Never crashes the page and never
    reveals passwords or connection details."""
    try:
        row = query_one("SELECT VERSION() AS version")
        return True, f"Database connected (MySQL {row['version']})."
    except Exception as error:
        # Details go to the terminal for you, not to the browser.
        current_app.logger.warning("Database check failed: %s", error)
        return False, "Cannot connect to the database. Check the terminal for details."