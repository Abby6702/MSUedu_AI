"""The AI learning assistant: a page plus small JSON endpoints (students only)."""
from flask import Blueprint, current_app, g, jsonify, render_template, request
from app.ai import ollama_client, prompts
from app.auth_utils import role_required
from app.services import ai_service, chat_service, learning_service, subject_service
from app.timeutil import format_local
from app.validators import clean

assistant_bp = Blueprint("assistant", __name__, url_prefix="/student/assistant")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _not_found():
    return _error("Conversation not found.", 404)


def _subjects_by_id():
    return {s["id"]: s["name"] for s in subject_service.list_subjects()}


def _optional_id(value):
    """(number, None), (None, None) when empty, or (None, 'message') when invalid."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "Invalid choice."
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None, "Invalid choice."
    return (number, None) if number > 0 else (None, "Invalid choice.")


def _conversation_json(conv):
    return {"id": conv["id"], "title": conv["title"], "subject_id": conv["subject_id"],
            "lesson_id": conv["lesson_id"], "subject_name": conv.get("subject_name") or "",
            "lesson_title": conv.get("lesson_title") or ""}


def _system_for(conv):
    """The tutor's instructions, plus the subject and lesson this conversation is about."""
    lesson = None
    if conv["lesson_id"]:
        try:
            lesson = learning_service.get_lesson(conv["lesson_id"], g.user["id"])
        except Exception:
            current_app.logger.exception("Could not load the lesson for a conversation")
    return prompts.teaching_system(conv.get("subject_name"), lesson)


def _read_message(body):
    """(text, None) or (None, error message)."""
    if not isinstance(body, dict):
        return None, "Send your question as JSON."
    text = body.get("message")
    if not isinstance(text, str) or not text.strip():
        return None, "Type a question first."
    text = text.strip()
    if len(text) > ai_service.MAX_MESSAGE:
        return None, f"Please keep your question under {ai_service.MAX_MESSAGE} characters."
    return text, None


# ---------- the page ----------
@assistant_bp.route("/")
@role_required("student")
def page():
    try:
        subjects = subject_service.list_subjects()
    except Exception:
        subjects = []
    try:
        lessons = learning_service.list_lessons_for_select()
    except Exception:
        current_app.logger.exception("Could not load lessons for the AI tutor")
        lessons = []
    return render_template("assistant/assistant.html", subjects=subjects, lessons=lessons,
                           max_message=ai_service.MAX_MESSAGE, max_notes=ai_service.MAX_NOTES)


@assistant_bp.route("/status")
@role_required("student")
def status():
    """Tells the page whether the AI is usable. Reveals no addresses, model names or keys."""
    return jsonify(ollama_client.check_status())


# ---------- saved conversations ----------
@assistant_bp.route("/conversations", methods=["GET", "POST"])
@role_required("student")
def conversations():
    user_id = g.user["id"]
    if request.method == "GET":
        items = [{"id": r["id"], "title": r["title"],
                  "context": r["lesson_title"] or r["subject_name"] or "",
                  "updated": format_local(r["updated_at"])}
                 for r in chat_service.list_conversations(user_id)]
        return jsonify({"ok": True, "conversations": items})

    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    lesson_id, problem = _optional_id(body.get("lesson_id"))
    subject_raw, problem2 = _optional_id(body.get("subject_id"))
    if problem or problem2:
        return _error("Choose a subject or lesson from the list.")

    subject_id = None
    if lesson_id is not None:
        lesson = learning_service.get_lesson(lesson_id, user_id)
        if lesson is None:
            return _error("Choose a lesson from the list.")
        subject_id = lesson["subject_id"]            # the lesson decides the subject
    elif subject_raw is not None:
        if subject_raw not in _subjects_by_id():
            return _error("Choose a subject from the list.")
        subject_id = subject_raw

    if chat_service.count_conversations(user_id) >= chat_service.MAX_CONVERSATIONS:
        return _error(f"You have {chat_service.MAX_CONVERSATIONS} saved conversations. "
                      "Delete an old one to start a new one.")
    new_id = chat_service.create_conversation(user_id, subject_id, lesson_id)
    return jsonify({"ok": True, "conversation": _conversation_json(
        chat_service.get_conversation(new_id, user_id))})


@assistant_bp.route("/conversations/<int:conversation_id>")
@role_required("student")
def conversation_detail(conversation_id):
    conv = chat_service.get_conversation(conversation_id, g.user["id"])
    if conv is None:
        return _not_found()
    messages = [{"role": m["role"], "content": m["content"]}
                for m in chat_service.all_messages(conversation_id)]
    return jsonify({"ok": True, "conversation": _conversation_json(conv), "messages": messages})


@assistant_bp.route("/conversations/<int:conversation_id>/messages", methods=["POST"])
@role_required("student")
def send_message(conversation_id):
    conv = chat_service.get_conversation(conversation_id, g.user["id"])
    if conv is None:
        return _not_found()
    text, problem = _read_message(request.get_json(silent=True))
    if problem:
        return _error(problem)
    if chat_service.count_messages(conversation_id) >= chat_service.MAX_MESSAGES:
        return _error("This conversation is full. Start a new conversation to continue.")

    # History comes from the DATABASE, never from the browser.
    history = chat_service.recent_messages(conversation_id, ai_service.MAX_HISTORY)
    messages = chat_service.build_messages(_system_for(conv), history, text)
    status_code, payload = ai_service._run(g.user["id"], "chat", conv["subject_id"], messages)
    if not payload.get("ok"):
        return jsonify(payload), status_code          # nothing is saved when the AI fails
    try:
        chat_service.add_exchange(conversation_id, text, payload["reply"])
    except Exception:
        current_app.logger.exception("Could not save a conversation exchange")
        return _error("The answer could not be saved. Please try again.", 500)
    return jsonify({"ok": True, "reply": payload["reply"]})


@assistant_bp.route("/conversations/<int:conversation_id>/regenerate", methods=["POST"])
@role_required("student")
def regenerate(conversation_id):
    conv = chat_service.get_conversation(conversation_id, g.user["id"])
    if conv is None:
        return _not_found()
    history = chat_service.recent_messages(conversation_id, ai_service.MAX_HISTORY + 1)
    if len(history) < 2 or history[-1]["role"] != "assistant" or history[-2]["role"] != "user":
        return _error("There is no answer to regenerate yet.")
    last = history[-1]
    messages = chat_service.build_messages(_system_for(conv), history[:-1])   # ends with the question
    status_code, payload = ai_service._run(g.user["id"], "chat", conv["subject_id"], messages,
                                           temperature=0.7)
    if not payload.get("ok"):
        return jsonify(payload), status_code
    try:
        chat_service.replace_reply(conversation_id, last["id"], payload["reply"])
    except Exception:
        current_app.logger.exception("Could not save a regenerated answer")
        return _error("The answer could not be saved. Please try again.", 500)
    return jsonify({"ok": True, "reply": payload["reply"]})


@assistant_bp.route("/conversations/<int:conversation_id>/clear", methods=["POST"])
@role_required("student")
def clear(conversation_id):
    if chat_service.get_conversation(conversation_id, g.user["id"]) is None:
        return _not_found()
    chat_service.clear_messages(conversation_id, g.user["id"])
    return jsonify({"ok": True})


@assistant_bp.route("/conversations/<int:conversation_id>/delete", methods=["POST"])
@role_required("student")
def delete_conversation(conversation_id):
    if chat_service.get_conversation(conversation_id, g.user["id"]) is None:
        return _not_found()
    chat_service.delete_conversation(conversation_id, g.user["id"])
    return jsonify({"ok": True})


# ---------- kept from Phase 5 (the page no longer uses it, its tests still do) ----------
@assistant_bp.route("/chat", methods=["POST"])
@role_required("student")
def chat():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send your question as JSON.")

    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("Type a question first.")
    message = message.strip()
    if len(message) > ai_service.MAX_MESSAGE:
        return _error(f"Please keep your question under {ai_service.MAX_MESSAGE} characters.")

    subject_id, subject_name = None, None
    raw_subject = body.get("subject_id")
    if raw_subject not in (None, ""):
        try:
            subject_id = int(raw_subject)
            subject_name = _subjects_by_id().get(subject_id)
        except (TypeError, ValueError):
            subject_name = None
        if subject_name is None:
            return _error("Choose a subject from the list.")

    topic = body.get("topic")
    topic = clean(topic)[:100] if isinstance(topic, str) else ""

    status_code, payload = ai_service.chat_reply(
        g.user["id"], subject_id, subject_name, topic, message, body.get("history"))
    return jsonify(payload), status_code


@assistant_bp.route("/summarize", methods=["POST"])
@role_required("student")
def summarize():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send your notes as JSON.")

    notes = body.get("notes")
    if not isinstance(notes, str) or len(notes.strip()) < 50:
        return _error("Paste at least a few sentences of notes (50 characters or more).")
    notes = notes.strip()
    if len(notes) > ai_service.MAX_NOTES:
        return _error(f"Please keep your notes under {ai_service.MAX_NOTES} characters.")

    length = body.get("length")
    if length not in ("brief", "detailed"):
        return _error("Choose brief or detailed.")

    status_code, payload = ai_service.summarize_notes(g.user["id"], notes, length)
    return jsonify(payload), status_code