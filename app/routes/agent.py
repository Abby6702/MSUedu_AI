"""The tutoring coordinator: a page plus small JSON endpoints. Students only."""
from datetime import datetime

from flask import Blueprint, g, jsonify, render_template, request

from app.auth_utils import role_required
from app.services import agent_service

agent_bp = Blueprint("agent", __name__, url_prefix="/student/agent")
MAX_MESSAGE = 500


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@agent_bp.route("/")
@role_required("student")
def page():
    return render_template("agent/agent.html", max_message=MAX_MESSAGE)


@agent_bp.route("/message", methods=["POST"])
@role_required("student")
def message():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send your message as JSON.")
    text = body.get("message")
    if not isinstance(text, str) or not text.strip():
        return _error("Type a message first.")
    text = text.strip()
    if len(text) > MAX_MESSAGE:
        return _error(f"Please keep your message under {MAX_MESSAGE} characters.")
    status, payload = agent_service.run_agent(g.user["id"], text)
    return jsonify(payload), status


@agent_bp.route("/prepare", methods=["POST"])
@role_required("student")
def prepare():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send your choice as JSON.")
    numbers = {}
    for key in ("tutor_id", "subject_id", "duration"):
        value = body.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return _error("That choice is not valid.")
        numbers[key] = value
    topic, fmt, start_text = body.get("topic"), body.get("format"), body.get("start")
    if not all(isinstance(x, str) for x in (topic, fmt, start_text)):
        return _error("That choice is not valid.")
    try:
        start = datetime.fromisoformat(start_text)
    except ValueError:
        return _error("That choice is not valid.")
    if start.tzinfo is not None:
        return _error("That choice is not valid.")
    status, payload = agent_service.prepare_choice(
        g.user["id"], numbers["tutor_id"], numbers["subject_id"], topic.strip(), fmt,
        start, numbers["duration"])
    return jsonify(payload), status


@agent_bp.route("/proposals/<int:proposal_id>/confirm", methods=["POST"])
@role_required("student")
def confirm(proposal_id):
    status, payload = agent_service.confirm_proposal(g.user["id"], proposal_id)
    return jsonify(payload), status


@agent_bp.route("/proposals/<int:proposal_id>/discard", methods=["POST"])
@role_required("student")
def discard(proposal_id):
    status, payload = agent_service.discard(g.user["id"], proposal_id)
    return jsonify(payload), status