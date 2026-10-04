"""Server-side checks for the 'generate a quiz' form."""
from app.validators import clean

DIFFICULTIES = ("easy", "medium", "hard")
MODES = ("practice", "test")
TYPES = ("mcq", "tf", "short")
MIN_QUESTIONS, MAX_QUESTIONS = 3, 10


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_generate_form(form, valid_subject_ids, topics=None):
    """Returns (data, errors). `topics` maps topic id -> {"subject_id": .., "name": ..}.
    `data` is safe to show back in the form."""
    errors = []

    subject_id = _to_int(form.get("subject_id"))
    if subject_id not in valid_subject_ids:
        errors.append("Choose a subject from the list.")

    topic = clean(form.get("topic"))
    topic_id = _to_int(form.get("topic_id"))
    if topic_id is not None:
        chosen = (topics or {}).get(topic_id)
        if chosen is None or chosen["subject_id"] != subject_id:
            errors.append("Choose a lesson topic that belongs to the chosen subject.")
            topic_id = None
        elif not topic:
            topic = chosen["name"]          # blank topic text: use the lesson topic's name
    if not 2 <= len(topic) <= 100:
        errors.append("Topic must be 2 to 100 characters.")

    difficulty = form.get("difficulty", "")
    if difficulty not in DIFFICULTIES:
        errors.append("Choose a difficulty.")
        difficulty = "medium"

    count = _to_int(form.get("count"))
    if count is None or not MIN_QUESTIONS <= count <= MAX_QUESTIONS:
        errors.append(f"Choose between {MIN_QUESTIONS} and {MAX_QUESTIONS} questions.")
        count = 5

    types = []
    for value in form.getlist("types"):
        if value in TYPES and value not in types:
            types.append(value)
    if not types:
        errors.append("Choose at least one question type.")

    mode = form.get("mode", "")
    if mode not in MODES:
        errors.append("Choose a quiz mode.")
        mode = "practice"

    data = {"subject_id": subject_id, "topic_id": topic_id, "topic": topic,
            "difficulty": difficulty, "count": count, "types": types or list(TYPES), "mode": mode}
    return data, errors