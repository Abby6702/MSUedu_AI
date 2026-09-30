"""Asks the AI for a quiz, validates it, saves it. Only VALIDATED questions are saved.
It reuses the rate limit, the usage log and the friendly error messages from Phase 5."""
import time
from flask import current_app
from app.ai import ollama_client, quiz_logic, quiz_prompts
from app.services import ai_service, quiz_service

QUIZ_MAX_TOKENS = 2500      # quizzes are long; the normal chat limit would cut the JSON off
BAD_FORMAT = ("The AI did not produce a usable quiz this time. Please try again, "
              "ask for fewer questions, or choose a simpler topic.")


def generate_quiz(user_id, subject_id, subject_name, data):
    """Returns (http_status, body). body is {"ok": True, "quiz_id": n, "count": n}
    or {"ok": False, "error": "..."}."""
    if ai_service._rate_limited(user_id):
        return 429, {"ok": False, "error": "You have sent a lot of requests. "
                                           "Please wait a few minutes and try again."}
    started = time.monotonic()
    messages = [
        {"role": "system", "content": quiz_prompts.SYSTEM},
        {"role": "user", "content": quiz_prompts.build_user_prompt(
            subject_name, data["topic"], data["difficulty"], data["count"], data["types"])},
    ]

    try:
        text = ollama_client.chat(messages, temperature=0.4, json_mode=True,
                                  max_tokens=QUIZ_MAX_TOKENS)
    except ollama_client.OllamaError as error:
        ai_service._log_usage(user_id, "quiz", subject_id, False, error.code, started)
        return (ai_service.STATUS_CODES.get(error.code, 502),
                {"ok": False, "error": ai_service.ERROR_MESSAGES.get(
                    error.code, ai_service.ERROR_MESSAGES["error"])})
    except Exception:
        current_app.logger.exception("Unexpected error while generating a quiz")
        ai_service._log_usage(user_id, "quiz", subject_id, False, "error", started)
        return 502, {"ok": False, "error": ai_service.ERROR_MESSAGES["error"]}

    try:
        questions = quiz_logic.parse_quiz(text, data["count"], data["types"])
    except quiz_logic.QuizFormatError:
        ai_service._log_usage(user_id, "quiz", subject_id, False, "bad_format", started)
        return 502, {"ok": False, "error": BAD_FORMAT}

    try:
        quiz_id = quiz_service.create_quiz(user_id, subject_id, data["topic"],
                                           data["difficulty"], data["mode"], questions)
    except Exception:
        current_app.logger.exception("Saving the quiz failed")
        ai_service._log_usage(user_id, "quiz", subject_id, False, "db_error", started)
        return 500, {"ok": False, "error": "The quiz could not be saved. Please try again."}

    ai_service._log_usage(user_id, "quiz", subject_id, True, None, started)
    return 200, {"ok": True, "quiz_id": quiz_id, "count": len(questions)}