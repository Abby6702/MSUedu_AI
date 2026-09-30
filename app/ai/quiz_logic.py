"""Pure functions (no database, no network) that check AI output and grade answers.
Because they are pure, they are easy to test."""
import json
import math
import random
import re


class QuizFormatError(Exception):
    """The AI output could not be turned into a usable quiz."""


# ---------- reading the AI's JSON ----------
def extract_json(text):
    if not isinstance(text, str):
        raise QuizFormatError("no text")
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except ValueError:
            pass
    raise QuizFormatError("not valid JSON")


def _text(value, low, high):
    """A cleaned string of the right length, or None."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value if low <= len(value) <= high else None


def _as_index(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and 0 <= value <= 3:
        return value
    return None


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def normalize_text(text):
    """For comparing short answers: ignore capitals, commas and quotes, extra spaces,
    a final full stop and a leading the/a/an. Decimal points inside numbers are kept,
    so '3.5' and '35' stay different."""
    text = re.sub(r"[,;:!?\"'“”‘’`]", "", (text or "").lower())
    text = " ".join(text.split()).rstrip(".")
    return re.sub(r"^(the|a|an)\s+", "", text)


# ---------- checking one question ----------
def clean_question(raw, allowed_types, rng):
    """Returns a clean question dict, or None if this question is not acceptable."""
    if not isinstance(raw, dict):
        return None
    q_type = raw.get("type")
    if q_type not in allowed_types:
        return None
    question = _text(raw.get("question"), 5, 500)
    explanation = _text(raw.get("explanation"), 3, 800)
    if not question or not explanation:
        return None

    base = {"type": q_type, "question": question, "explanation": explanation,
            "options": None, "accepted": None}

    if q_type == "mcq":
        options = raw.get("options")
        if not isinstance(options, list) or len(options) != 4:
            return None
        cleaned = [_text(o, 1, 200) for o in options]
        if None in cleaned or len({o.lower() for o in cleaned}) != 4:
            return None
        index = _as_index(raw.get("answer_index"))
        if index is None:
            return None
        correct_text = cleaned[index]
        rng.shuffle(cleaned)                          # do not trust the AI's option order
        base["options"] = cleaned
        base["correct"] = str(cleaned.index(correct_text))
        return base

    if q_type == "tf":
        answer = _as_bool(raw.get("answer"))
        if answer is None:
            return None
        base["correct"] = "true" if answer else "false"
        return base

    # short answer
    answer = _text(raw.get("answer"), 1, 200)
    if not answer:
        return None
    accepted, seen = [], {normalize_text(answer)}
    extra = raw.get("accepted_answers")
    for item in (extra if isinstance(extra, list) else [])[:5]:
        item = _text(item, 1, 200)
        if item and normalize_text(item) not in seen:
            seen.add(normalize_text(item))
            accepted.append(item)
    base["correct"] = answer
    base["accepted"] = accepted or None
    return base


def parse_quiz(text, requested, allowed_types, rng=None):
    """Returns a list of clean questions, or raises QuizFormatError."""
    rng = rng or random.Random()
    data = extract_json(text)
    items = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise QuizFormatError("no questions")

    questions, seen = [], set()
    for raw in items:
        question = clean_question(raw, allowed_types, rng)
        if question is None:
            continue
        key = normalize_text(question["question"])
        if key in seen:
            continue
        seen.add(key)
        questions.append(question)
        if len(questions) == requested:
            break

    if len(questions) < math.ceil(requested / 2):     # too many were unusable
        raise QuizFormatError("too few usable questions")
    return questions


# ---------- grading ----------
def grade_answer(q_type, correct, accepted, submitted):
    """True if the submitted answer is right. Runs only on the server."""
    if not isinstance(submitted, str):
        return False
    given = submitted.strip()
    if q_type == "mcq":
        return given == correct
    if q_type == "tf":
        return given.lower() == correct
    if q_type == "short":
        given_norm = normalize_text(given)
        if not given_norm:
            return False
        return any(normalize_text(option) == given_norm
                   for option in [correct] + list(accepted or []))
    return False