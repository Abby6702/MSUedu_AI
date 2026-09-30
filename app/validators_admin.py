"""Server-side checks for admin filters and settings."""
import re
from app.validators import clean

REQUEST_STATUSES = ("pending", "accepted", "declined", "reschedule_proposed",
                    "completed", "cancelled")
ACTION_RE = re.compile(r"^[a-z_]{1,60}$")
MAX_ANNOUNCEMENT = 300


def parse_page(args):
    raw = args.get("page", "")
    return min(int(raw), 10000) if raw.isdigit() and int(raw) >= 1 else 1


def parse_user_filters(args):
    role, status = args.get("role", ""), args.get("status", "")
    return {"q": clean(args.get("q"))[:100],
            "role": role if role in ("student", "tutor", "admin") else "",
            "status": status if status in ("active", "inactive") else ""}


def parse_request_status(args):
    status = args.get("status", "")
    return status if status in REQUEST_STATUSES else ""


def parse_feedback_filter(args):
    show = args.get("show", "")
    return show if show in ("visible", "hidden") else ""


def parse_audit_action(args):
    action = args.get("action", "")
    return action if ACTION_RE.match(action) else ""


def validate_settings(form):
    """Returns (values, errors). The announcement is plain text (it is escaped when shown)."""
    announcement = clean(form.get("announcement"))
    errors = []
    if len(announcement) > MAX_ANNOUNCEMENT:
        errors.append(f"The announcement must be {MAX_ANNOUNCEMENT} characters or fewer.")
    return {"announcement": announcement,
            "registration_open": "true" if form.get("registration_open") == "on" else "false"}, errors