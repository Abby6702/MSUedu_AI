"""Feedback, session records (tutor), and the student's learning progress."""
from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, url_for)
from app import validators_progress as vp
from app.ai import progress_prompts
from app.auth_utils import role_required
from app.services import ai_service, notification_service, quiz_service
from app.services import progress_service as ps

progress_bp = Blueprint("progress", __name__)


def _safe_notify(*args):
    """Extra notifications are a bonus: never let them break the main action."""
    try:
        notification_service.notify(*args)
    except Exception:
        current_app.logger.exception("Could not create a notification")


# ---------- student: feedback ----------
@progress_bp.route("/student/sessions/<int:request_id>/feedback", methods=["GET", "POST"])
@role_required("student")
def feedback(request_id):
    sess = ps.get_completed_for_student(request_id, g.user["id"])
    if sess is None:
        abort(404)                       # not yours, not completed, or it does not exist
    existing = ps.get_feedback(request_id)
    record = ps.get_record(request_id)
    errors, data = [], {}

    if request.method == "POST" and existing is None:
        data, errors = vp.validate_feedback(request.form)
        if not errors:
            try:
                ps.create_feedback(request_id, g.user["id"], sess["tutor_id"],
                                   data["rating"], data["comment"])
            except ps.FeedbackExists:
                flash("You already sent feedback for this session.", "info")
                return redirect(url_for("progress.feedback", request_id=request_id))
            except Exception:
                current_app.logger.exception("Saving feedback failed")
                errors.append("Could not save your feedback. Please try again.")
            else:
                _safe_notify(sess["tutor_id"], "feedback_new", "New feedback received",
                             f"A student rated a {sess['subject_name']} session "
                             f"{data['rating']} out of 5.", "/tutor/feedback",
                             f"feedback:{request_id}")
                flash("Thank you! Your feedback was sent.", "success")
                return redirect(url_for("bookings.my_requests"))

    return render_template("progress/feedback_form.html", s=sess, existing=existing,
                           record=record, errors=errors, data=data)


# ---------- student: progress ----------
@progress_bp.route("/student/progress")
@role_required("student")
def my_progress():
    sessions, quizzes, counts, error = [], [], {}, None
    try:
        sessions = ps.student_completed_sessions(g.user["id"])
        quizzes = quiz_service.list_quizzes(g.user["id"])
        counts = ps.activity_counts(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load progress")
        error = "Could not load your progress. Please try again."
    return render_template("progress/progress.html", sessions=sessions, quizzes=quizzes,
                           counts=counts, error=error)


# ---------- tutor: feedback about me ----------
@progress_bp.route("/tutor/feedback")
@role_required("tutor")
def tutor_feedback():
    items, summary, error = [], {"n": 0, "avg": None}, None
    try:
        items = ps.tutor_feedback(g.user["id"])
        summary = ps.rating_summary(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load feedback")
        error = "Could not load your feedback. Please try again."
    return render_template("progress/tutor_feedback.html", items=items, summary=summary, error=error)


# ---------- tutor: record a completed session ----------
@progress_bp.route("/tutor/sessions/<int:request_id>/record", methods=["GET", "POST"])
@role_required("tutor")
def record(request_id):
    sess = ps.get_completed_for_tutor(request_id, g.user["id"])
    if sess is None:
        abort(404)
    errors = []

    if request.method == "POST":
        data, errors = vp.validate_record(request.form)
        if not errors:
            try:
                ps.save_record(request_id, g.user["id"], data)
            except Exception:
                current_app.logger.exception("Saving the session record failed")
                errors.append("Could not save. Please try again.")
            else:
                _safe_notify(sess["student_id"], "record_shared", "Your tutor added session notes",
                             f"{sess['tutor_name']} recorded what you covered in "
                             f"{sess['subject_name']}.", "/student/progress",
                             f"record:{request_id}")
                flash("Session record saved. The student can now see it.", "success")
                return redirect(url_for("bookings.tutor_requests"))
    else:
        existing = ps.get_record(request_id) or {}
        data = {"topics_covered": existing.get("topics_covered", ""),
                "outcomes": existing.get("outcomes", ""),
                "next_steps": existing.get("next_steps") or "",
                "summary_text": existing.get("summary_text") or "",
                "ai_assisted": bool(existing.get("summary_ai_assisted"))}

    return render_template("progress/record_form.html", s=sess, data=data, errors=errors)


@progress_bp.route("/tutor/sessions/<int:request_id>/summary", methods=["POST"])
@role_required("tutor")
def summary(request_id):
    """Optional AI DRAFT of a recap. It is only a draft: the tutor reads, edits and saves."""
    if ps.get_completed_for_tutor(request_id, g.user["id"]) is None:
        return jsonify({"ok": False, "error": "Session not found."}), 404
    values, problem = vp.validate_summary_input(request.get_json(silent=True))
    if problem:
        return jsonify({"ok": False, "error": problem}), 400
    messages = [
        {"role": "system", "content": progress_prompts.summary_system()},
        {"role": "user", "content": progress_prompts.summary_user(
            values["topics"], values["outcomes"], values["next_steps"])},
    ]
    status, payload = ai_service._run(g.user["id"], "session_summary", None, messages)
    return jsonify(payload), status