"""In-app notifications and session reminders."""
from datetime import timedelta
from app.db import execute, get_connection, query_all, query_one
from app.timeutil import format_local, format_range_local, utcnow

DEFAULT_HOURS = [24, 1]

EVENT_SELECT = """
SELECT r.id, r.student_id, r.tutor_id, r.topic, r.start_at, r.end_at,
       r.proposed_start_at, r.proposed_end_at, r.response_note,
       s.name AS subject_name, su.full_name AS student_name, tu.full_name AS tutor_name
FROM tutoring_requests r
JOIN subjects s ON s.id = r.subject_id
JOIN users su ON su.id = r.student_id
JOIN users tu ON tu.id = r.tutor_id
"""


# ---------- rules (no database, easy to test) ----------
def parse_hours(text):
    """'24,1' -> [1, 24]. Bad values are ignored. Falls back to [1, 24]."""
    hours = set()
    for part in (text or "").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 168:
            hours.add(int(part))
    return sorted(hours)[:4] or sorted(DEFAULT_HOURS)


def pick_threshold(start, now, hours):
    """The TIGHTEST reminder window that applies, or None. A session 5 hours away with
    windows [1, 24] gives 24 (not both), so one reminder is sent at a time."""
    if start <= now:
        return None
    remaining = start - now
    for h in sorted(hours):
        if remaining <= timedelta(hours=h):
            return h
    return None


def build_request_notification(r, event, actor_id):
    """Returns (recipient_id, kind, title, body, link) or None. Pure function."""
    subject, topic = r["subject_name"], r["topic"]
    when = format_range_local(r["start_at"], r["end_at"])
    student_page, tutor_page = "/student/requests", "/tutor/requests"

    if event == "created":
        return (r["tutor_id"], "request_new", "New tutoring request",
                f"{r['student_name']} asked for help with {subject} ({topic}) on {when}.",
                tutor_page)
    if event == "accepted":
        return (r["student_id"], "request_accepted", "Request accepted",
                f"{r['tutor_name']} accepted your {subject} request. Session: {when}.",
                student_page)
    if event == "declined":
        body = f"{r['tutor_name']} declined your {subject} request."
        if r.get("response_note"):
            body += f" Note: {r['response_note']}"
        return (r["student_id"], "request_declined", "Request declined", body, student_page)
    if event == "proposed":
        new = format_range_local(r["proposed_start_at"], r["proposed_end_at"])
        return (r["student_id"], "request_proposed", "New time proposed",
                f"{r['tutor_name']} suggested {new} for your {subject} request. "
                "Open your requests to accept or cancel.", student_page)
    if event == "proposal_accepted":
        return (r["tutor_id"], "proposal_accepted", "New time accepted",
                f"{r['student_name']} accepted the new time for {subject}: {when}.", tutor_page)
    if event == "cancelled":
        by_student = actor_id == r["student_id"]
        recipient = r["tutor_id"] if by_student else r["student_id"]
        who = r["student_name"] if by_student else r["tutor_name"]
        return (recipient, "request_cancelled", "Request or session cancelled",
                f"{who} cancelled the {subject} request ({when}).",
                tutor_page if by_student else student_page)
    if event == "completed":
        return (r["student_id"], "session_completed", "Session completed",
                f"Your {subject} session with {r['tutor_name']} was marked completed. "
                "You can now leave feedback.", f"/student/sessions/{r['id']}/feedback")
    return None


# ---------- saving and reading ----------
def notify(user_id, kind, title, body, link, dedupe_key):
    """Save a notification. Returns True if it is NEW, False if the same event was
    already saved (the unique key on user_id + dedupe_key blocks duplicates)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            added = cur.execute(
                "INSERT IGNORE INTO notifications (user_id, kind, title, body, link, "
                "dedupe_key, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, kind, title[:150], body[:500], link, dedupe_key[:80], utcnow()),
            )
        conn.commit()
        return added == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def request_event(request_id, event, actor_id):
    """Create the notification for something that happened to a request."""
    row = query_one(EVENT_SELECT + " WHERE r.id = %s", (request_id,))
    if row is None:
        return False
    built = build_request_notification(row, event, actor_id)
    if built is None:
        return False
    recipient, kind, title, body, link = built
    return notify(recipient, kind, title, body, link, f"req:{request_id}:{event}")


def list_for_user(user_id, limit=50):
    return query_all(
        "SELECT id, kind, title, body, link, is_read, created_at FROM notifications "
        "WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT %s", (user_id, limit))


def unread_count(user_id):
    return query_one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = 0",
                     (user_id,))["n"]


def get_own(notification_id, user_id):
    return query_one("SELECT id, link, is_read FROM notifications WHERE id = %s AND user_id = %s",
                     (notification_id, user_id))


def mark_read(notification_id, user_id):
    execute("UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s",
            (notification_id, user_id))


def mark_all_read(user_id):
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0", (user_id,))


def reminders_enabled(user_id):
    row = query_one("SELECT reminders_enabled FROM notification_preferences WHERE user_id = %s",
                    (user_id,))
    return True if row is None else bool(row["reminders_enabled"])


def set_reminders_enabled(user_id, enabled):
    execute("INSERT INTO notification_preferences (user_id, reminders_enabled) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE reminders_enabled = VALUES(reminders_enabled)",
            (user_id, 1 if enabled else 0))


# ---------- reminders ----------
def send_due_reminders(hours, now=None):
    """Remind both people about accepted sessions that are coming up.
    Returns how many NEW reminders were saved. Running it twice sends nothing twice."""
    now = now or utcnow()
    horizon = now + timedelta(hours=max(hours))
    sessions = query_all(
        EVENT_SELECT + " WHERE r.status = 'accepted' AND r.start_at > %s AND r.start_at <= %s",
        (now, horizon))
    muted = {row["user_id"] for row in query_all(
        "SELECT user_id FROM notification_preferences WHERE reminders_enabled = 0")}

    sent = 0
    for r in sessions:
        h = pick_threshold(r["start_at"], now, hours)
        if h is None:
            continue
        when = format_local(r["start_at"])
        # The start time is part of the key, so a session moved to a new time can be reminded again.
        key = f"remind:{r['id']}:{h}:{r['start_at']:%m%d%H%M}"
        for user_id, other, link in ((r["student_id"], r["tutor_name"], "/student/requests"),
                                     (r["tutor_id"], r["student_name"], "/tutor/requests")):
            if user_id in muted:
                continue
            if notify(user_id, "reminder", f"Reminder: {r['subject_name']} session coming up",
                      f"Your session with {other} starts {when} (Philippine time).", link, key):
                sent += 1
    return sent