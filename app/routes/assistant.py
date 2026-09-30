"""The AI learning assistant: a page plus three small JSON endpoints."""
from flask import Blueprint, g, jsonify, render_template, request
from app.ai import ollama_client
from app.auth_utils import role_required
from app.services import ai_service, subject_service
from app.validators import clean

assistant_bp = Blueprint("assistant", __name__, url_prefix="/student/assistant")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _subjects_by_id():
    return {s["id"]: s["name"] for s in subject_service.list_subjects()}


@assistant_bp.route("/")
@role_required("student")
def page():
    try:
        subjects = subject_service.list_subjects()
    except Exception:
        subjects = []
    return render_template("assistant/assistant.html", subjects=subjects,
                           max_message=ai_service.MAX_MESSAGE, max_notes=ai_service.MAX_NOTES)


@assistant_bp.route("/status")
@role_required("student")
def status():
    """Tells the page whether the AI is usable. Reveals no addresses or model names."""
    return jsonify(ollama_client.check_status())


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