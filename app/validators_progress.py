"""Server-side checks for feedback, session records and the AI-summary request."""


def _multiline(value):
    return (value or "").strip() if isinstance(value, str) else ""


def validate_feedback(form):
    errors = []
    raw = (form.get("rating") or "").strip()
    rating = int(raw) if raw.isdigit() and 1 <= int(raw) <= 5 else None
    if rating is None:
        errors.append("Choose a rating from 1 to 5.")
    comment = _multiline(form.get("comment"))
    if len(comment) > 1000:
        errors.append("The comment must be 1000 characters or fewer.")
    return {"rating": rating, "comment": comment}, errors


def validate_record(form):
    errors = []
    topics = _multiline(form.get("topics_covered"))
    outcomes = _multiline(form.get("outcomes"))
    next_steps = _multiline(form.get("next_steps"))
    summary = _multiline(form.get("summary_text"))

    if not 3 <= len(topics) <= 500:
        errors.append("Topics covered must be 3 to 500 characters.")
    if not 3 <= len(outcomes) <= 1000:
        errors.append("Learning outcomes must be 3 to 1000 characters.")
    if len(next_steps) > 500:
        errors.append("Next steps must be 500 characters or fewer.")
    if len(summary) > 1500:
        errors.append("The recap must be 1500 characters or fewer.")

    data = {"topics_covered": topics, "outcomes": outcomes, "next_steps": next_steps,
            "summary_text": summary,
            "ai_assisted": form.get("ai_assisted") == "1" and bool(summary)}
    return data, errors


def validate_summary_input(body):
    """For the AI recap request (JSON). Returns (values, error_message_or_None)."""
    if not isinstance(body, dict):
        return None, "Send the notes as JSON."
    topics, outcomes = _multiline(body.get("topics")), _multiline(body.get("outcomes"))
    next_steps = _multiline(body.get("next_steps"))
    if not 3 <= len(topics) <= 500:
        return None, "Fill in the topics covered first (3 to 500 characters)."
    if not 3 <= len(outcomes) <= 1000:
        return None, "Fill in the learning outcomes first (3 to 1000 characters)."
    if len(next_steps) > 500:
        return None, "Next steps must be 500 characters or fewer."
    return {"topics": topics, "outcomes": outcomes, "next_steps": next_steps}, None