"""Server-side checks for the curriculum forms."""
import unicodedata

from app.validators import clean

LEVELS = (1, 2, 3, 4)
DIFFICULTIES = ("easy", "medium", "hard")
MIN_BODY, MAX_BODY = 20, 8000


def _int(value):
    return int(value.strip()) if isinstance(value, str) and value.strip().isdigit() else None


def clean_body(text):
    """Lesson text: normal line breaks, no control or invisible formatting characters (this also
    removes right-to-left override tricks). Indentation inside the text is kept."""
    if not isinstance(text, str):
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return text.strip("\n").rstrip()


def validate_topic(form):
    """Returns (data, errors). A blank position means 'place the topic last in its level'."""
    errors = []
    name = clean(form.get("name"))
    if not 2 <= len(name) <= 100:
        errors.append("Topic name must be 2 to 100 characters.")
    level = _int(form.get("level"))
    if level not in LEVELS:
        errors.append("Choose a level from 1 to 4.")
        level = 1
    position = None
    raw = (form.get("position") or "").strip()
    if raw:
        position = _int(raw)
        if position is None or not 1 <= position <= 99:
            errors.append("Position must be a number from 1 to 99, or left empty to place the topic last.")
            position = None
    return {"name": name, "level": level, "position": position}, errors


def validate_lesson(form):
    errors = []
    title = clean(form.get("title"))
    if not 3 <= len(title) <= 150:
        errors.append("Lesson title must be 3 to 150 characters.")
    body = clean_body(form.get("body"))
    if not MIN_BODY <= len(body) <= MAX_BODY:
        errors.append(f"Lesson text must be {MIN_BODY} to {MAX_BODY} characters.")
    difficulty = form.get("difficulty", "")
    if difficulty not in DIFFICULTIES:
        errors.append("Choose a difficulty.")
        difficulty = "easy"
    minutes = _int(form.get("minutes"))
    if minutes is None or not 1 <= minutes <= 120:
        errors.append("Reading time must be 1 to 120 minutes.")
        minutes = 5
    return {"title": title, "body": body, "difficulty": difficulty, "minutes": minutes}, errors