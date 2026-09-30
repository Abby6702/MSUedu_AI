"""Pure functions (no database, no network) for the agent: reading the plan,
resolving days, matching subjects and computing REAL open time slots."""
import difflib
import re
from datetime import datetime, timedelta

from app.ai import quiz_logic
from app.timeutil import format_range_local, local_to_utc
from app.validators_request import DURATIONS, MAX_AHEAD, MIN_LEAD
from app.validators_tutor import parse_hhmm

INTENTS = ("find_tutor", "reschedule", "cancel", "status", "other")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PARTS_OF_DAY = {                       # allowed START times for each part of the day
    "morning": (timedelta(hours=6), timedelta(hours=12)),
    "afternoon": (timedelta(hours=12), timedelta(hours=18)),
    "evening": (timedelta(hours=18), timedelta(hours=22)),
}
STEP = timedelta(minutes=30)
WINDOW_DAYS = 14


def normalize(text):
    return " ".join((text or "").lower().split())


# ---------- reading the plan ----------
def parse_intent(raw_text):
    """Turn the model's JSON into a CLEAN plan, or None. Unknown keys are ignored,
    so the model can never smuggle in extra instructions."""
    try:
        data = quiz_logic.extract_json(raw_text)
    except quiz_logic.QuizFormatError:
        return None
    if not isinstance(data, dict) or data.get("intent") not in INTENTS:
        return None

    def text(key, limit):
        value = data.get(key)
        return " ".join(value.split())[:limit] if isinstance(value, str) else ""

    part = text("part_of_day", 12).lower()
    fmt = text("format", 12).lower()
    duration = data.get("duration_minutes")
    return {
        "intent": data["intent"],
        "subject": text("subject", 100),
        "topic": text("topic", 100),
        "day": text("day", 12).lower(),
        "time": parse_hhmm(text("time", 5)),                 # timedelta or None
        "part_of_day": part if part in PARTS_OF_DAY else "",
        "duration": duration if isinstance(duration, int) and duration in DURATIONS else 60,
        "format": fmt if fmt in ("online", "in_person") else "",
    }


def resolve_days(day, today):
    """Returns (list_of_dates, problem). `today` is a Philippine-time date."""
    window = [today + timedelta(days=i) for i in range(WINDOW_DAYS)]
    if not day:
        return window, None
    if day == "today":
        return [today], None
    if day == "tomorrow":
        return [today + timedelta(days=1)], None
    if day in WEEKDAYS:
        return [d for d in window if d.weekday() == WEEKDAYS.index(day)], None
    try:
        chosen = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return [], "I could not understand that day. Try a weekday like Monday, or a date like 2026-10-06."
    if chosen < today or chosen > today + timedelta(days=60):
        return [], "I can only look at dates from today up to 60 days ahead."
    return [chosen], None


# ---------- matching names ----------
def match_subject(text, subjects):
    """Match the student's words to ONE real subject, or return None."""
    wanted = normalize(text)
    if not wanted:
        return None
    by_name = {normalize(s["name"]): s for s in subjects}
    if wanted in by_name:
        return by_name[wanted]
    hits = [s for name, s in by_name.items() if len(wanted) >= 3 and (wanted in name or name in wanted)]
    if len(hits) == 1:
        return hits[0]
    if hits:
        return None                       # ambiguous: "calculus" could be Calculus 1 or 2
    close = difflib.get_close_matches(wanted, list(by_name), n=1, cutoff=0.7)
    return by_name[close[0]] if close else None


def find_subject_in_message(message, subjects):
    """Fallback: exactly one subject name appears in the message."""
    text = normalize(message)
    hits = [s for s in subjects if normalize(s["name"]) in text]
    return hits[0] if len(hits) == 1 else None


def extract_request_id(message):
    found = re.search(r"#\s*(\d{1,9})", message or "")
    return int(found.group(1)) if found else None


# ---------- REAL open time slots ----------
def _hhmm(offset):
    minutes = int(offset.total_seconds()) // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def compute_open_slots(weekly, busy, dates, duration, now_utc,
                       time_pref=None, part_of_day="", limit=4):
    """weekly: the tutor's weekly slots (Philippine time). busy: [(start_utc, end_utc)] of
    confirmed sessions. Returns a few open [start, end) times in UTC, spread over the days."""
    length = timedelta(minutes=duration)
    earliest, latest = now_utc + MIN_LEAD, now_utc + MAX_AHEAD
    window = PARTS_OF_DAY.get(part_of_day)

    found = []
    for day in sorted(dates):
        todays = sorted((w for w in weekly if w["day_of_week"] == day.weekday()),
                        key=lambda w: w["start_time"])
        for slot in todays:
            t = slot["start_time"]
            while t + length <= slot["end_time"]:
                wanted = True
                if window and not (window[0] <= t < window[1]):
                    wanted = False
                if wanted and time_pref is not None and abs(t - time_pref) > timedelta(minutes=60):
                    wanted = False
                if wanted:
                    start = local_to_utc(day.isoformat(), _hhmm(t))
                    if start is not None:
                        end = start + length
                        free = not any(start < b_end and end > b_start for b_start, b_end in busy)
                        if free and earliest <= start <= latest:
                            found.append({"day": day, "start": start, "end": end})
                t += STEP

    # Take the first time of each day before the second time of any day (better variety).
    ranked, seen = [], {}
    for s in sorted(found, key=lambda s: s["start"]):
        n = seen.get(s["day"], 0)
        seen[s["day"]] = n + 1
        ranked.append((n, s["start"], s))
    ranked.sort(key=lambda r: (r[0], r[1]))
    picked = sorted((r[2] for r in ranked[:limit]), key=lambda s: s["start"])
    return [{"start": s["start"], "end": s["end"]} for s in picked]


# ---------- sentences built from real data ----------
def describe_preferences(intent, fmt_time):
    parts = []
    day = intent["day"]
    if day in ("today", "tomorrow"):
        parts.append(day)
    elif day:
        parts.append("on " + day.capitalize())
    else:
        parts.append("in the next two weeks")
    if intent["time"] is not None:
        parts.append("around " + fmt_time(intent["time"]))
    if intent["part_of_day"]:
        parts.append("in the " + intent["part_of_day"])
    return " ".join(parts)


def describe_request(r):
    base = f"#{r['id']} {r['subject_name']} with {r['tutor_name']}"
    when = format_range_local(r["start_at"], r["end_at"])
    status = r["status"]
    if status == "pending":
        return f"{base}: waiting for the tutor to reply. Requested time: {when}."
    if status == "reschedule_proposed":
        new = format_range_local(r["proposed_start_at"], r["proposed_end_at"])
        return (f"{base}: the tutor proposed a new time ({new}). Open My requests to accept "
                "or cancel it. I cannot accept for you.")
    if status == "accepted":
        return f"{base}: confirmed for {when}."
    text = f"{base}: {status.replace('_', ' ')}."
    if status == "declined" and r.get("response_note"):
        text += f" The tutor's note: {r['response_note']}"
    return text