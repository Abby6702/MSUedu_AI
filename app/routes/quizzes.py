"""Quizzes: generate, take, get graded, review, practice again."""
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)
from app import validators_quiz as vq
from app.auth_utils import role_required
from app.services import quiz_generator, quiz_service as qs, subject_service

quizzes_bp = Blueprint("quizzes", __name__, url_prefix="/student/quizzes")

DEFAULT_FORM = {"subject_id": None, "topic": "", "difficulty": "medium",
                "count": 5, "types": ["mcq", "tf", "short"], "mode": "practice"}


def _render_index(errors, data, status=200):
    errors = list(errors)
    try:
        subjects = subject_service.list_subjects()
    except Exception:
        current_app.logger.exception("Could not load subjects")
        subjects = []
        errors.append("Could not load the subject list.")
    try:
        quizzes = qs.list_quizzes(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load past quizzes")
        quizzes = []
        errors.append("Could not load your past quizzes.")
    return render_template("quizzes/index.html", subjects=subjects, quizzes=quizzes,
                           data=data, errors=errors, limits=(vq.MIN_QUESTIONS, vq.MAX_QUESTIONS)), status


@quizzes_bp.route("/")
@role_required("student")
def index():
    return _render_index([], dict(DEFAULT_FORM))


@quizzes_bp.route("/generate", methods=["POST"])
@role_required("student")
def generate():
    try:
        subjects = subject_service.list_subjects()
    except Exception:
        current_app.logger.exception("Could not load subjects")
        return _render_index(["The subject list could not be loaded. Please try again."],
                             dict(DEFAULT_FORM), 503)
    names = {s["id"]: s["name"] for s in subjects}

    data, errors = vq.validate_generate_form(request.form, set(names))
    if errors:
        return _render_index(errors, data, 400)

    status, body = quiz_generator.generate_quiz(
        g.user["id"], data["subject_id"], names[data["subject_id"]], data)
    if not body.get("ok"):
        return _render_index([body["error"]], data, status)

    if body["count"] < data["count"]:
        flash(f"The AI produced {body['count']} usable questions "
              f"(you asked for {data['count']}).", "info")
    else:
        flash("Your quiz is ready.", "success")
    return redirect(url_for("quizzes.take", quiz_id=body["quiz_id"]))


@quizzes_bp.route("/<int:quiz_id>/take")
@role_required("student")
def take(quiz_id):
    quiz = qs.get_quiz(quiz_id, g.user["id"])
    if quiz is None:
        abort(404)                          # not yours, or it does not exist
    return render_template("quizzes/take.html", quiz=quiz,
                           questions=qs.get_questions_for_taking(quiz_id))


@quizzes_bp.route("/<int:quiz_id>/submit", methods=["POST"])
@role_required("student")
def submit(quiz_id):
    quiz = qs.get_quiz(quiz_id, g.user["id"])
    if quiz is None:
        abort(404)
    try:
        attempt_id = qs.save_attempt(quiz, g.user["id"], request.form)
    except Exception:
        current_app.logger.exception("Saving a quiz attempt failed")
        flash("Your answers could not be saved. Please try again.", "error")
        return redirect(url_for("quizzes.take", quiz_id=quiz_id))
    return redirect(url_for("quizzes.result", attempt_id=attempt_id))


@quizzes_bp.route("/attempts/<int:attempt_id>")
@role_required("student")
def result(attempt_id):
    attempt, items = qs.get_attempt_review(attempt_id, g.user["id"])
    if attempt is None:
        abort(404)
    return render_template("quizzes/result.html", attempt=attempt, items=items)


@quizzes_bp.route("/attempts/<int:attempt_id>/reveal", methods=["POST"])
@role_required("student")
def reveal(attempt_id):
    try:
        qs.reveal_attempt(attempt_id, g.user["id"])
    except Exception:
        current_app.logger.exception("Revealing answers failed")
        flash("Could not show the answers. Please try again.", "error")
    return redirect(url_for("quizzes.result", attempt_id=attempt_id))


@quizzes_bp.route("/<int:quiz_id>/history")
@role_required("student")
def history(quiz_id):
    quiz = qs.get_quiz(quiz_id, g.user["id"])
    if quiz is None:
        abort(404)
    return render_template("quizzes/history.html", quiz=quiz,
                           attempts=qs.list_attempts(quiz_id, g.user["id"]))