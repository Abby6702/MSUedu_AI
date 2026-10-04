"""Runs the tutor's AI requests: rate limit, call, check the output, log counts only.
The student's name and chat never reach a prompt. Only the subject, the session topic and what
the tutor typed are used."""
import time

from flask import current_app

from app.ai import ollama_client, tutor_logic, tutor_prompts
from app.services import ai_service, summary_service

FEATURE = "tutor_assist"
BAD_FORMAT = "The AI did not produce a usable result this time. Please try again, or make your request simpler."
RATE_MESSAGE = "You have sent a lot of requests. Please wait a few minutes and try again."


def _call(user_id, feature, subject_id, system, user, parser=None, json_mode=False,
          max_tokens=None, temperature=0.4):
    """Returns (http_status, error_body_or_None, result)."""
    if ai_service._rate_limited(user_id):
        return 429, {"ok": False, "error": RATE_MESSAGE}, None
    started = time.monotonic()
    kwargs = {"temperature": temperature}
    if json_mode:
        kwargs["json_mode"] = True
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        text = ollama_client.chat(messages, **kwargs)
    except ollama_client.OllamaError as error:
        ai_service._log_usage(user_id, feature, subject_id, False, error.code, started)
        return (ai_service.STATUS_CODES.get(error.code, 502),
                {"ok": False, "error": ai_service.ERROR_MESSAGES.get(error.code, ai_service.ERROR_MESSAGES["error"])},
                None)
    except Exception:
        current_app.logger.exception("Unexpected error in a tutor AI request")
        ai_service._log_usage(user_id, feature, subject_id, False, "error", started)
        return 502, {"ok": False, "error": ai_service.ERROR_MESSAGES["error"]}, None

    result = text
    if parser is not None:
        try:
            result = parser(text)
        except tutor_logic.TutorAiFormatError:
            ai_service._log_usage(user_id, feature, subject_id, False, "bad_format", started)
            return 502, {"ok": False, "error": BAD_FORMAT}, None
    ai_service._log_usage(user_id, feature, subject_id, True, None, started)
    return 200, None, result


def _lessons(subject_id):
    try:
        return summary_service.lessons_for_subject(subject_id), None
    except Exception:
        current_app.logger.exception("Could not load lessons for a tutor AI request")
        return None, (500, {"ok": False, "error": "Could not load the lessons. Please try again."})


def assist(user_id, sess, data):
    """One panel action. Returns (http_status, json_body)."""
    action, subject, subject_id = data["action"], sess["subject_name"], sess["subject_id"]

    if action in ("exercises", "explain", "hint"):
        if action == "exercises":
            system, user = tutor_prompts.exercises(subject, data["topic"], data["level"],
                                                   data["count"], data["include_answers"])
            tokens = 1500
        elif action == "explain":
            system, user = tutor_prompts.explain(subject, data["topic"], data["level"])
            tokens = 1200
        else:
            system, user = tutor_prompts.hint(subject, data["problem"], data["attempt"])
            tokens = 900
        status, error, result = _call(user_id, FEATURE, subject_id, system, user,
                                      max_tokens=tokens, temperature=0.5)
        return (status, error) if error else (200, {"ok": True, "kind": "text", "text": result})

    if action == "quiz":
        system, user = tutor_prompts.quiz(subject, data["topic"], data["difficulty"], data["count"], data["types"])
        status, error, result = _call(
            user_id, FEATURE, subject_id, system, user, json_mode=True, max_tokens=2500,
            parser=lambda t: tutor_logic.parse_quiz_result(t, data["count"], data["types"]))
        return (status, error) if error else (200, {"ok": True, "kind": "quiz", "questions": result})

    # next_lesson
    lessons, failure = _lessons(subject_id)
    if failure:
        return failure
    if not lessons:
        return 409, {"ok": False, "error": "This subject has no lessons yet, so there is nothing to recommend."}
    allowed = {l["id"] for l in lessons}
    system, user = tutor_prompts.next_lesson(subject, sess["topic"], data["notes"], lessons)
    status, error, result = _call(user_id, FEATURE, subject_id, system, user, json_mode=True,
                                  max_tokens=300, temperature=0.2,
                                  parser=lambda t: tutor_logic.parse_lesson_pick(t, allowed))
    if error:
        return status, error
    lesson = next(l for l in lessons if l["id"] == result["lesson_id"])
    return 200, {"ok": True, "kind": "lesson", "reason": result["reason"],
                 "lesson": {"id": lesson["id"], "title": lesson["title"], "topic": lesson["topic_name"]}}


def summary_draft(user_id, sess, notes):
    """The AI's draft of the structured summary, from the tutor's own notes only."""
    lessons, failure = _lessons(sess["subject_id"])
    if failure:
        return failure
    allowed = {l["id"] for l in lessons}
    system, user = tutor_prompts.summary_draft(sess["subject_name"], sess["topic"], notes, lessons)
    status, error, result = _call(user_id, "session_summary", sess["subject_id"], system, user,
                                  json_mode=True, max_tokens=700, temperature=0.3,
                                  parser=lambda t: tutor_logic.parse_summary_draft(t, allowed))
    return (status, error) if error else (200, {"ok": True, "draft": result})