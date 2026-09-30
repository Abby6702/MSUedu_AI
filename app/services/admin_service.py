"""Database work for the administrator pages. Nothing here reads or returns
passwords or password hashes."""
import math
from datetime import timedelta
from app.db import get_connection, query_all, query_one
from app.services import user_service
from app.services.tutor_service import like_pattern
from app.timeutil import utcnow

PAGE_SIZE = 25


def percent(part, whole):
    return round(100 * part / whole) if whole else None


def _clamp_page(total, page):
    pages = max(1, math.ceil(total / PAGE_SIZE))
    return min(max(page, 1), pages)


def _offset(page):
    return (page - 1) * PAGE_SIZE


def _change(sql, params):
    """Run an UPDATE and return how many rows actually changed."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            changed = cur.execute(sql, params)
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- overview and reports ----------
def overview():
    stats = query_one(
        "SELECT "
        "(SELECT COUNT(*) FROM tutor_profiles tp JOIN users u ON u.id = tp.user_id "
        "  WHERE tp.approval_status = 'approved' AND u.is_active = 1) AS approved_tutors, "
        "(SELECT COUNT(*) FROM tutor_profiles WHERE approval_status = 'pending') AS pending_tutors, "
        "(SELECT COUNT(*) FROM subjects WHERE is_active = 1) AS active_subjects, "
        "(SELECT COUNT(*) FROM tutoring_requests) AS requests_total, "
        "(SELECT COUNT(*) FROM tutoring_requests "
        "  WHERE status IN ('pending','reschedule_proposed')) AS requests_open, "
        "(SELECT COUNT(*) FROM tutoring_requests WHERE status = 'completed') AS sessions_completed, "
        "(SELECT COUNT(*) FROM feedback WHERE is_hidden = 0) AS feedback_visible, "
        "(SELECT COUNT(*) FROM users WHERE is_active = 0) AS inactive_users")
    stats["users"] = user_service.count_users_by_role()
    return stats


def reports(days=30):
    cutoff = utcnow() - timedelta(days=days)
    ai = query_all(
        "SELECT feature, COUNT(*) AS total, SUM(success) AS ok FROM ai_usage_logs "
        "WHERE created_at > %s GROUP BY feature ORDER BY feature", (cutoff,))
    for row in ai:                                   # counts only: no content is ever stored
        row["ok"] = int(row["ok"] or 0)
        row["rate"] = percent(row["ok"], row["total"])
    ratings = query_one("SELECT COUNT(*) AS n, AVG(rating) AS avg FROM feedback WHERE is_hidden = 0")
    return {
        "days": days,
        "by_status": query_all("SELECT status, COUNT(*) AS n FROM tutoring_requests "
                               "GROUP BY status ORDER BY n DESC"),
        "tutors": query_all("SELECT approval_status, COUNT(*) AS n FROM tutor_profiles "
                            "GROUP BY approval_status"),
        "per_subject": query_all(
            "SELECT s.name, COUNT(*) AS n FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
            "WHERE r.status = 'completed' GROUP BY s.id, s.name ORDER BY n DESC, s.name LIMIT 10"),
        "ratings": {"n": ratings["n"],
                    "avg": round(float(ratings["avg"]), 1) if ratings["n"] and ratings["avg"] is not None else None},
        "ai": ai,
        "proposals": query_all("SELECT status, COUNT(*) AS n FROM agent_proposals GROUP BY status"),
    }


# ---------- users ----------
def _user_where(f):
    """Fixed SQL pieces only. What the admin typed travels in `params`."""
    where, params = ["1 = 1"], []
    if f["role"]:
        where.append("u.role = %s")
        params.append(f["role"])
    if f["status"]:
        where.append("u.is_active = %s")
        params.append(1 if f["status"] == "active" else 0)
    if f["q"]:
        like = like_pattern(f["q"])
        where.append("(u.full_name LIKE %s OR u.email LIKE %s)")
        params += [like, like]
    return " AND ".join(where), params


def list_users(filters, page):
    where, params = _user_where(filters)
    total = query_one(f"SELECT COUNT(*) AS n FROM users u WHERE {where}", params)["n"]
    page = _clamp_page(total, page)
    rows = query_all(
        "SELECT u.id, u.full_name, u.email, u.role, u.is_active, u.created_at, u.last_login_at, "
        "tp.approval_status FROM users u LEFT JOIN tutor_profiles tp ON tp.user_id = u.id "
        f"WHERE {where} ORDER BY u.created_at DESC, u.id DESC LIMIT %s OFFSET %s",
        params + [PAGE_SIZE, _offset(page)])
    return rows, total, page


def get_manageable_user(user_id):
    """Only students and tutors. Admin accounts are never returned, so an admin
    cannot lock out or reset another administrator here."""
    return query_one("SELECT id, full_name, email, role, is_active FROM users "
                     "WHERE id = %s AND role IN ('student', 'tutor')", (user_id,))


def set_active(user_id, active):
    """Also bumps session_version, which ends the person's existing sessions."""
    return _change("UPDATE users SET is_active = %s, session_version = session_version + 1 "
                   "WHERE id = %s AND role IN ('student', 'tutor')",
                   (1 if active else 0, user_id)) == 1


def reset_password(user_id, password_hash):
    return _change("UPDATE users SET password_hash = %s, must_change_password = 1, "
                   "session_version = session_version + 1 "
                   "WHERE id = %s AND role IN ('student', 'tutor')",
                   (password_hash, user_id)) == 1


# ---------- requests, feedback, audit ----------
def list_requests(status, page):
    where, params = "1 = 1", []
    if status:
        where, params = "r.status = %s", [status]
    total = query_one(f"SELECT COUNT(*) AS n FROM tutoring_requests r WHERE {where}", params)["n"]
    page = _clamp_page(total, page)
    rows = query_all(
        "SELECT r.id, r.topic, r.status, r.session_format, r.start_at, r.end_at, "
        "s.name AS subject_name, su.full_name AS student_name, tu.full_name AS tutor_name "
        "FROM tutoring_requests r JOIN subjects s ON s.id = r.subject_id "
        "JOIN users su ON su.id = r.student_id JOIN users tu ON tu.id = r.tutor_id "
        f"WHERE {where} ORDER BY r.start_at DESC, r.id DESC LIMIT %s OFFSET %s",
        params + [PAGE_SIZE, _offset(page)])
    return rows, total, page


def list_feedback(show, page):
    where = {"hidden": "f.is_hidden = 1", "visible": "f.is_hidden = 0"}.get(show, "1 = 1")
    total = query_one(f"SELECT COUNT(*) AS n FROM feedback f WHERE {where}")["n"]
    page = _clamp_page(total, page)
    rows = query_all(
        "SELECT f.id, f.rating, f.comment, f.is_hidden, f.created_at, "
        "tu.full_name AS tutor_name, s.name AS subject_name "
        "FROM feedback f JOIN tutoring_requests r ON r.id = f.request_id "
        "JOIN subjects s ON s.id = r.subject_id JOIN users tu ON tu.id = f.tutor_id "
        f"WHERE {where} ORDER BY f.created_at DESC, f.id DESC LIMIT %s OFFSET %s",
        [PAGE_SIZE, _offset(page)])
    return rows, total, page


def set_feedback_hidden(feedback_id, hidden):
    """True only if something actually changed."""
    return _change("UPDATE feedback SET is_hidden = %s WHERE id = %s",
                   (1 if hidden else 0, feedback_id)) == 1


def list_audit(action, page):
    where, params = "1 = 1", []
    if action:
        where, params = "a.action = %s", [action]
    total = query_one(f"SELECT COUNT(*) AS n FROM audit_logs a WHERE {where}", params)["n"]
    page = _clamp_page(total, page)
    rows = query_all(
        "SELECT a.id, a.action, a.target_type, a.target_id, a.details, a.created_at, "
        "u.full_name AS actor_name FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_user_id "
        f"WHERE {where} ORDER BY a.id DESC LIMIT %s OFFSET %s",
        params + [PAGE_SIZE, _offset(page)])
    return rows, total, page


def audit_actions():
    return [r["action"] for r in query_all("SELECT DISTINCT action FROM audit_logs ORDER BY action")]