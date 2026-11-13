"""Server-side checks for tutor setup, availability, subjects and search filters."""
import re
from datetime import timedelta
from app.validators import clean

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FORMATS = ("online", "in_person", "both")
SORT_KEYS = ("name", "newest", "slots")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MIN_SLOT_MINUTES = 30
RATE_DURATIONS = (30, 60, 90, 120)
PAYMENT_METHODS = ("gcash", "maya", "bank_transfer")


def parse_hhmm(text):
    """'14:30' -> timedelta(hours=14, minutes=30). Returns None if invalid."""
    match = TIME_RE.match((text or "").strip())
    if not match:
        return None
    return timedelta(hours=int(match.group(1)), minutes=int(match.group(2)))


def _to_int(value, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def validate_slot(form):
    errors = []
    day = _to_int(form.get("day_of_week"), 0, 6)
    start = parse_hhmm(form.get("start_time"))
    end = parse_hhmm(form.get("end_time"))
    if day is None:
        errors.append("Choose a day of the week.")
    if start is None or end is None:
        errors.append("Enter valid start and end times.")
    elif end <= start:
        errors.append("The end time must be after the start time.")
    elif (end - start) < timedelta(minutes=MIN_SLOT_MINUTES):
        errors.append(f"A slot must be at least {MIN_SLOT_MINUTES} minutes long.")
    return {"day": day, "start": start, "end": end}, errors


def validate_teaching_setup(form, valid_subject_ids):
    """Returns (format, [(subject_id, topics)], errors)."""
    errors = []
    tutoring_format = form.get("tutoring_format", "")
    if tutoring_format not in FORMATS:
        errors.append("Choose a tutoring format.")

    selections, seen = [], set()
    for raw in form.getlist("subject_ids"):
        if not raw.isdigit() or int(raw) not in valid_subject_ids:
            errors.append("One of the selected subjects is not available.")
            continue
        subject_id = int(raw)
        if subject_id in seen:
            continue
        seen.add(subject_id)
        topics = clean(form.get(f"topics_{subject_id}"))
        if len(topics) > 255:
            errors.append("Topics must be 255 characters or fewer for each subject.")
        selections.append((subject_id, topics))

    if not selections:
        errors.append("Select at least one subject you can teach.")
    if len(selections) > 15:
        errors.append("You can select at most 15 subjects.")
    return tutoring_format, selections, errors


def validate_subject_rates(form, subject_ids):
    """Returns per-subject rates keyed by duration, plus validation errors."""
    rates, errors = {}, []
    for subject_id in subject_ids:
        subject_rates = {}
        for duration in RATE_DURATIONS:
            rate = _to_int(form.get(f"rate_{duration}_{subject_id}"), 1, 100000)
            if rate is None:
                errors.append(f"Enter a whole-number price from ₱1 to ₱100,000 for each {duration}-minute session.")
            else:
                subject_rates[duration] = rate
        rates[subject_id] = subject_rates
    return rates, errors


def validate_payment_details(form):
    data = {
        "method": form.get("payment_method", ""),
        "account_name": clean(form.get("payment_account_name")),
        "account_number": clean(form.get("payment_account_number")),
    }
    errors = []
    if data["method"] not in PAYMENT_METHODS:
        errors.append("Choose a supported payment method.")
    if not 2 <= len(data["account_name"]) <= 100:
        errors.append("Payment account name must be 2 to 100 characters.")
    if not 4 <= len(data["account_number"]) <= 50:
        errors.append("Payment account number must be 4 to 50 characters.")
    return data, errors


def validate_new_subject_request(form):
    """Validate a tutor's proposed catalog subject and its initial rates."""
    data = {
        "name": clean(form.get("subject_name")),
        "category": clean(form.get("subject_category")),
        "topics": clean(form.get("subject_topics")),
    }
    errors = []
    if not 2 <= len(data["name"]) <= 100:
        errors.append("Subject name must be 2 to 100 characters.")
    if len(data["category"]) > 60:
        errors.append("Category must be 60 characters or fewer.")
    if len(data["topics"]) > 255:
        errors.append("Topics must be 255 characters or fewer.")
    rates = {}
    for duration in RATE_DURATIONS:
        rate = _to_int(form.get(f"new_rate_{duration}"), 1, 100000)
        if rate is None:
            errors.append(f"Enter a whole-number price from ₱1 to ₱100,000 for each {duration}-minute session.")
        else:
            rates[duration] = rate
    data["rates"] = rates
    return data, errors


def validate_subject_form(form):
    data = {"name": clean(form.get("name")), "category": clean(form.get("category"))}
    errors = []
    if not 2 <= len(data["name"]) <= 100:
        errors.append("Subject name must be 2 to 100 characters.")
    if len(data["category"]) > 60:
        errors.append("Category must be 60 characters or fewer.")
    return data, errors


def parse_search_args(args):
    """Turns the URL query (?q=...&day=...) into safe, known-good values."""
    fmt = args.get("format", "")
    sort = args.get("sort", "name")
    return {
        "q": clean(args.get("q"))[:100],
        "subject_id": _to_int(args.get("subject_id"), 1, 2**31 - 1),
        "course": clean(args.get("course"))[:100],
        "day": _to_int(args.get("day"), 0, 6),
        "format": fmt if fmt in ("online", "in_person") else "",
        "sort": sort if sort in SORT_KEYS else "name",
    }