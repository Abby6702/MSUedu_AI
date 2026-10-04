"""The tutor's AI panel, structured session summaries, and the student's view of a shared summary."""
from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, url_for)
from app import validators_tutor_ai as vta
from app.auth_utils import role_required
from app.services import live_logic
from app.services import notification_service
from app.services import summary_service as ss
from app.services import tutor_ai_service
from app.timeutil import utcnow

session_ai_bp = Blueprint("session_ai", __name__)


def _error(message, status):
    return jsonify({"ok": False, "error": message}), status


def _started(sess):
    """A summary can be written once a confirmed or completed session has started."""
    return sess["status"] in ("accepted", "completed") and sess["start_at"] <= utcnow()


def _safe_notify(*args):
    """A notification problem must never undo a saved summary."""
    try:
        notification_service.notify(*args)
    except Exception:
        current_app.logger.exception("Could not create a notification")


# ---------- the AI panel in the live room (tutor only) ----------
@session_ai_bp.route("/sessions/<int:request_id>/assistant", methods=["POST"])
@role_required("tutor")
def assistant(request_id):
    sess = ss.get_session_for_tutor(request_id, g.user["id"])
    if sess is None:
        return _error("Session not found.", 404)
    state, _message = live_logic.join_state(sess["status"], sess["start_at"], sess["end_at"], utcnow())
    if state != "open":
        return _error("The AI assistant is available while the session room is open.", 403)
    data, problem = vta.validate_assist(request.get_json(silent=True), sess["topic"])
    if problem:
        return _error(problem, 400)
    status, payload = tutor_ai_service.assist(g.user["id"], sess, data)
    return jsonify(payload), status


# ---------- the structured summary (tutor) ----------
@session_ai_bp.route("/tutor/sessions/<int:request_id>/session-summary", methods=["GET", "POST"])
@role_required("tutor")
def summary(request_id):
    sess = ss.get_session_for_tutor(request_id, g.user["id"])
    if sess is None:
        abort(404)
    if not _started(sess):
        flash("The summary can be written once the session has started.", "error")
        return redirect(url_for("bookings.tutor_requests"))
    try:
        lessons = ss.lessons_for_subject(sess["subject_id"])
        existing = ss.get_summary(request_id)
        quick_topics = "" if existing else ss.record_topics(request_id)
    except Exception:
        current_app.logger.exception("Could not load the session summary page")
        flash("Could not load the summary page. Please try again.", "error")
        return redirect(url_for("bookings.tutor_requests"))
    errors = []

    if request.method == "POST":
        data, errors = vta.validate_summary_form(request.form, {l["id"] for l in lessons})
        action = request.form.get("action")
        if action not in ("share", "draft"):
            errors.append("Choose Save as draft or Save and share.")
        if not errors:
            share = action == "share"
            try:
                ss.save_summary(request_id, g.user["id"], data, share)
            except Exception:
                current_app.logger.exception("Saving a session summary failed")
                errors.append("Could not save the summary. Please try again.")
            else:
                if share:
                    _safe_notify(sess["student_id"], "summary_shared", "Your tutor shared a session summary",
                                 f"{sess['tutor_name']} shared a summary of your {sess['subject_name']} session.",
                                 url_for("session_ai.student_summary", request_id=request_id),
                                 f"summary:{request_id}")
                flash("Summary saved and shared with the student." if share
                      else "Draft saved. The student cannot see it yet.", "success")
                return redirect(url_for("bookings.tutor_requests"))
        status = None
    else:
        data = {"topics_covered": (existing or {}).get("topics_covered") or quick_topics,
                "strengths": (existing or {}).get("strengths") or "",
                "improvements": (existing or {}).get("improvements") or "",
                "practice": (existing or {}).get("practice") or "",
                "next_lesson_id": (existing or {}).get("next_lesson_id"),
                "ai_assisted": bool((existing or {}).get("ai_assisted"))}
        status = (existing or {}).get("status")

    return render_template("session_ai/summary_form.html", sess=sess, lessons=lessons,
                           data=data, errors=errors, status=status)


@session_ai_bp.route("/tutor/sessions/<int:request_id>/session-summary/draft", methods=["POST"])
@role_required("tutor")
def summary_draft(request_id):
    sess = ss.get_session_for_tutor(request_id, g.user["id"])
    if sess is None:
        return _error("Session not found.", 404)
    if not _started(sess):
        return _error("A draft can be written once the session has started.", 403)
    notes, problem = vta.validate_draft_notes(request.get_json(silent=True))
    if problem:
        return _error(problem, 400)
    status, payload = tutor_ai_service.summary_draft(g.user["id"], sess, notes)
    return jsonify(payload), status


# ---------- the student's view ----------
@session_ai_bp.route("/student/sessions/<int:request_id>/session-summary")
@role_required("student")
def student_summary(request_id):
    item = ss.get_approved_for_student(request_id, g.user["id"])
    if item is None:
        abort(404)                       # not yours, not shared, or it does not exist
    return render_template("session_ai/student_summary.html", s=item)