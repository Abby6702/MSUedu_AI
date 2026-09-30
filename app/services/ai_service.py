"""Rules around AI use: validation, rate limiting, logging (metadata only) and
turning errors into friendly messages. Routes call this; it calls ollama_client."""
import time
from flask import current_app
from app.ai import ollama_client, prompts
from app.db import execute, query_one

MAX_MESSAGE = 2000
MAX_NOTES = 6000
MAX_HISTORY = 10
MAX_HISTORY_CHARS = 4000
RATE_LIMIT = 20          # requests ...
RATE_WINDOW_MIN = 10     # ... per this many minutes, per student

ERROR_MESSAGES = {
    "not_configured": "The AI model has not been set up yet. Please contact the administrator.",
    "unavailable": "The AI service is not running right now. Please try again later.",
    "model_missing": "The configured AI model is not installed on the server.",
    "timeout": "The AI took too long to answer. Try a shorter question, or try again.",
    "bad_response": "The AI returned an answer we could not use. Please try again.",
    "error": "Something went wrong with the AI service. Please try again.",
}
STATUS_CODES = {"not_configured": 503, "unavailable": 503, "model_missing": 503,
                "timeout": 504, "bad_response": 502, "error": 502}


def clean_history(raw):
    """Keep only well-formed user/assistant messages. A 'system' role from the
    browser is dropped, so the browser can never change the AI's rules."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[-MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content.strip()[:MAX_HISTORY_CHARS]})
    return cleaned


def _rate_limited(user_id):
    try:
        row = query_one(
            "SELECT COUNT(*) AS n FROM ai_usage_logs WHERE user_id = %s "
            "AND created_at > NOW() - INTERVAL %s MINUTE",
            (user_id, RATE_WINDOW_MIN),
        )
        return row["n"] >= RATE_LIMIT
    except Exception:
        current_app.logger.exception("Rate-limit check failed")
        return False            # if the check itself breaks, do not block students


def _log_usage(user_id, feature, subject_id, success, error_code, started):
    """Metadata only. Never pass message text in here."""
    try:
        execute(
            "INSERT INTO ai_usage_logs (user_id, feature, subject_id, success, error_code, "
            "duration_ms) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, feature, subject_id, 1 if success else 0, error_code,
             int((time.monotonic() - started) * 1000)),
        )
    except Exception:
        current_app.logger.exception("Could not write AI usage log")


def _run(user_id, feature, subject_id, messages):
    """Returns (http_status, json_body)."""
    if _rate_limited(user_id):
        return 429, {"ok": False, "error": "You have sent a lot of requests. "
                                           "Please wait a few minutes and try again."}
    started = time.monotonic()
    try:
        text = ollama_client.chat(messages)
    except ollama_client.OllamaError as error:
        _log_usage(user_id, feature, subject_id, False, error.code, started)
        return (STATUS_CODES.get(error.code, 502),
                {"ok": False, "error": ERROR_MESSAGES.get(error.code, ERROR_MESSAGES["error"])})
    except Exception:
        current_app.logger.exception("Unexpected AI error")
        _log_usage(user_id, feature, subject_id, False, "error", started)
        return 502, {"ok": False, "error": ERROR_MESSAGES["error"]}

    _log_usage(user_id, feature, subject_id, True, None, started)
    return 200, {"ok": True, "reply": text}


def chat_reply(user_id, subject_id, subject_name, topic, message, history):
    messages = [{"role": "system", "content": prompts.tutor_system(subject_name, topic)}]
    messages += clean_history(history)
    messages.append({"role": "user", "content": message})
    return _run(user_id, "chat", subject_id, messages)


def summarize_notes(user_id, notes, length):
    messages = [
        {"role": "system", "content": prompts.summary_system(length)},
        {"role": "user", "content": "Summarize these notes:\n\n" + notes},
    ]
    return _run(user_id, "summary", None, messages)