"""Pure functions (no database, no network) that check the AI's output for the tutor tools."""
from app.ai import quiz_logic


class TutorAiFormatError(Exception):
    """The AI's output could not be turned into something usable."""


def _json(text):
    try:
        return quiz_logic.extract_json(text)
    except quiz_logic.QuizFormatError:
        raise TutorAiFormatError("not valid JSON") from None


def clean_field(value, limit):
    """Text from the AI -> one tidy line of at most `limit` characters. A list becomes 'a; b'."""
    if isinstance(value, list):
        value = "; ".join(v for v in value if isinstance(v, str))
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _lesson_id(value, allowed):
    """A lesson id only if it is one of the real ones offered. Anything else becomes None."""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value in allowed else None


def parse_lesson_pick(text, allowed_ids):
    data = _json(text)
    if not isinstance(data, dict):
        raise TutorAiFormatError("not an object")
    lesson_id = _lesson_id(data.get("lesson_id"), allowed_ids)
    reason = clean_field(data.get("reason"), 300)
    if lesson_id is None or len(reason) < 5:
        raise TutorAiFormatError("no valid lesson")
    return {"lesson_id": lesson_id, "reason": reason}


def parse_summary_draft(text, allowed_ids):
    data = _json(text)
    if not isinstance(data, dict):
        raise TutorAiFormatError("not an object")
    topics = clean_field(data.get("topics_covered"), 600)
    if len(topics) < 3:
        raise TutorAiFormatError("no topics")
    return {"topics_covered": topics,
            "strengths": clean_field(data.get("strengths"), 600),
            "improvements": clean_field(data.get("improvements"), 600),
            "practice": clean_field(data.get("practice"), 600),
            "next_lesson_id": _lesson_id(data.get("next_lesson_id"), allowed_ids)}


def quiz_for_display(questions):
    """Validated quiz questions -> what the tutor sees, including the answers."""
    shown = []
    for q in questions:
        options = q["options"]
        if q["type"] == "mcq":
            answer = options[int(q["correct"])]
        elif q["type"] == "tf":
            answer = "True" if q["correct"] == "true" else "False"
        else:
            answer = q["correct"]
            if q.get("accepted"):
                answer += " (also accepted: " + ", ".join(q["accepted"]) + ")"
        shown.append({"type": q["type"], "question": q["question"], "options": options,
                      "answer": answer, "explanation": q["explanation"]})
    return shown


def parse_quiz_result(text, count, types):
    try:
        questions = quiz_logic.parse_quiz(text, count, tuple(types))
    except quiz_logic.QuizFormatError:
        raise TutorAiFormatError("no usable quiz") from None
    return quiz_for_display(questions)