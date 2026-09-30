"""Server-side checks for tutoring request forms."""
from datetime import timedelta
from app.timeutil import local_to_utc, utcnow
from app.validators import clean

DURATIONS = (30, 60, 90, 120)
FORMATS = ("online", "in_person")
MIN_LEAD = timedelta(hours=1)      # requests must be at least 1 hour ahead
MAX_AHEAD = timedelta(days=60)


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_when(form):
    """Returns (start_utc, end_utc, duration, errors)."""
    errors = []
    start = local_to_utc(form.get("date"), form.get("time"))
    duration = _int_or_none(form.get("duration"))
    if start is None:
        errors.append("Enter a valid date and time.")
    if duration not in DURATIONS:
        errors.append("Choose a session length from the list.")
    end = None
    if not errors:
        now = utcnow()
        if start < now + MIN_LEAD:
            errors.append("Choose a time at least 1 hour from now.")
        elif start > now + MAX_AHEAD:
            errors.append("You can only book up to 60 days ahead.")
        else:
            end = start + timedelta(minutes=duration)
    return start, end, duration, errors


def validate_request_form(form, valid_subject_ids):
    """Returns (data, errors). `data` also keeps the typed date/time for re-display."""
    errors = []
    subject_id = _int_or_none(form.get("subject_id"))
    if subject_id not in valid_subject_ids:
        errors.append("Choose one of the tutor's subjects.")

    topic = clean(form.get("topic"))
    if not 2 <= len(topic) <= 150:
        errors.append("Topic must be 2 to 150 characters.")

    description = (form.get("description") or "").strip()
    if len(description) > 1000:
        errors.append("The explanation must be 1000 characters or fewer.")

    fmt = form.get("format", "")
    if fmt not in FORMATS:
        errors.append("Choose online or in person.")

    start, end, duration, when_errors = validate_when(form)
    errors += when_errors

    data = {
        "subject_id": subject_id, "topic": topic, "description": description,
        "format": fmt, "start": start, "end": end,
        "date": form.get("date", ""), "time": form.get("time", ""),
        "duration": duration if duration is not None else form.get("duration", ""),
    }
    return data, errors