"""Server-side checks for the tutor's AI panel and the session summary form."""
from app.validators import clean

ACTIONS = ("exercises", "explain", "quiz", "hint", "next_lesson")
LEVELS = ("beginner", "intermediate", "advanced")
DIFFICULTIES = ("easy", "medium", "hard")
QUIZ_TYPES = ("mcq", "tf", "short")


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def validate_assist(body, default_topic):
    """Returns (data, error_message). data holds only the fields this action needs."""
    if not isinstance(body, dict):
        return None, "Send your request as JSON."
    action = body.get("action")
    if action not in ACTIONS:
        return None, "Choose what you want the assistant to do."
    data = {"action": action}

    if action in ("exercises", "explain", "quiz"):
        topic = clean(body.get("topic")) if isinstance(body.get("topic"), str) else ""
        if not topic:
            topic = clean(default_topic)[:100]
        if not 2 <= len(topic) <= 100:
            return None, "The topic must be 2 to 100 characters."
        data["topic"] = topic

    if action in ("exercises", "explain"):
        level = body.get("level") or "beginner"
        if level not in LEVELS:
            return None, "Choose a level."
        data["level"] = level

    if action == "exercises":
        count = _int(body.get("count")) if body.get("count") not in (None, "") else 5
        if count is None or not 1 <= count <= 8:
            return None, "Choose between 1 and 8 exercises."
        data["count"] = count
        data["include_answers"] = body.get("include_answers") is True

    if action == "quiz":
        count = _int(body.get("count")) if body.get("count") not in (None, "") else 5
        if count is None or not 3 <= count <= 8:
            return None, "Choose between 3 and 8 quiz questions."
        difficulty = body.get("difficulty") or "medium"
        if difficulty not in DIFFICULTIES:
            return None, "Choose a difficulty."
        raw_types = body.get("types")
        if raw_types in (None, []):
            types = list(QUIZ_TYPES)
        elif isinstance(raw_types, list) and all(t in QUIZ_TYPES for t in raw_types):
            types = [t for t in QUIZ_TYPES if t in raw_types]
        else:
            return None, "Choose valid question types."
        data.update(count=count, difficulty=difficulty, types=types)

    if action == "hint":
        problem, attempt = _text(body.get("problem")), _text(body.get("attempt"))
        if not 10 <= len(problem) <= 1500:
            return None, "Paste the problem (10 to 1500 characters)."
        if len(attempt) > 1000:
            return None, "What the student tried must be 1000 characters or fewer."
        data.update(problem=problem, attempt=attempt)

    if action == "next_lesson":
        notes = _text(body.get("notes"))
        if len(notes) > 1000:
            return None, "Your notes must be 1000 characters or fewer."
        data["notes"] = notes
    return data, None


def validate_draft_notes(body):
    """For the AI summary draft. Returns (notes, error_message)."""
    notes = _text(body.get("notes")) if isinstance(body, dict) else ""
    if not 20 <= len(notes) <= 2000:
        return None, "Write a few sentences of notes first (20 to 2000 characters)."
    return notes, None


def validate_summary_form(form, allowed_lesson_ids):
    """Returns (data, errors) for the structured summary form."""
    errors = []

    def field(name, label, required=False):
        value = (form.get(name) or "").strip()
        if required and len(value) < 3:
            errors.append(f"{label} is required (at least 3 characters).")
        elif len(value) > 600:
            errors.append(f"{label} must be 600 characters or fewer.")
        return value

    topics = field("topics_covered", "Topics covered", required=True)
    strengths = field("strengths", "Strengths")
    improvements = field("improvements", "Areas to improve")
    practice = field("practice", "Recommended practice")

    next_lesson_id = None
    raw = (form.get("next_lesson_id") or "").strip()
    if raw:
        number = int(raw) if raw.isdigit() else None
        if number in allowed_lesson_ids:
            next_lesson_id = number
        else:
            errors.append("Choose a lesson from the list.")

    ai_assisted = form.get("ai_assisted") == "1" and bool(topics or strengths or improvements or practice)
    return {"topics_covered": topics, "strengths": strengths, "improvements": improvements,
            "practice": practice, "next_lesson_id": next_lesson_id, "ai_assisted": ai_assisted}, errors