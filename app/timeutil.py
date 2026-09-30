"""Time helpers. Rule: the database stores UTC, people see Philippine time."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.validators_tutor import parse_hhmm

PH_TZ = ZoneInfo("Asia/Manila")


def utcnow():
    """Current time in UTC, without tzinfo (matches what MySQL DATETIME returns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt_utc):
    """Naive UTC datetime -> timezone-aware Philippine datetime."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(PH_TZ)


def local_to_utc(date_text, time_text):
    """('2026-10-06', '14:00') typed in Philippine time -> naive UTC datetime.
    Returns None if the text is not a valid date/time."""
    try:
        day = datetime.strptime((date_text or "").strip(), "%Y-%m-%d")
    except ValueError:
        return None
    offset = parse_hhmm(time_text)
    if offset is None:
        return None
    local = (day + offset).replace(tzinfo=PH_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _clock(local_dt):
    return local_dt.strftime("%I:%M %p").lstrip("0")


def format_local(dt_utc):
    if dt_utc is None:
        return ""
    local = to_local(dt_utc)
    return local.strftime("%a, %d %b %Y, ") + _clock(local)


def format_range_local(start_utc, end_utc):
    if start_utc is None or end_utc is None:
        return ""
    return f"{format_local(start_utc)} to {_clock(to_local(end_utc))} (PH time)"