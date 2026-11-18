from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, url_for
from app.auth_utils import role_required
from app.services import progress_service as ps
from app.services import quiz_service, recommendation_service
from app.services import request_service as rs
from app.services import tutor_service as tutors
from app.services import user_service as users

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.route("/dashboard")
@role_required("student")
def dashboard():
    profile = users.get_profile(g.user["id"], "student") or {}
    upcoming, pending, activity, recs = [], [], [], []
    try:
        groups = rs.grouped_requests(g.user["id"], "student")
        upcoming, pending = groups["upcoming"][:3], groups["attention"][:3]
        activity = quiz_service.recent_attempts(g.user["id"], 3)
        recs = recommendation_service.top_active(g.user["id"], 3)
    except Exception:
        current_app.logger.exception("Could not load dashboard data")
    return render_template("student/dashboard.html", recs=recs, profile=profile,
                           upcoming=upcoming, pending=pending, activity=activity)
                           


@student_bp.route("/tutors")
@role_required("student")
def find_tutors():
    results, error = [], None
    try:
        results = tutors.list_public_tutors()
    except Exception:
        current_app.logger.exception("Could not load tutor profiles")
        error = "Tutor profiles are temporarily unavailable. Please try again."
    return render_template("student/find_tutors.html", results=results,
                           format_labels=tutors.FORMAT_LABELS, error=error)


@student_bp.route("/match")
@role_required("student")
def match():
    return redirect(url_for("student.find_tutors"))


@student_bp.route("/tutors/<int:tutor_id>")
@role_required("student")
def tutor_detail(tutor_id):
    tutor = tutors.get_public_tutor(tutor_id)
    if tutor is None:
        abort(404)      # hidden, unapproved or inactive tutors look like they don't exist
    rating, feedback_items = {"n": 0, "avg": None}, []
    try:
        rating = ps.rating_summary(tutor_id)
        feedback_items = ps.tutor_feedback(tutor_id, 5)     # anonymous, visible feedback only
    except Exception:
        current_app.logger.exception("Could not load tutor feedback")
    return render_template("student/tutor_detail.html", tutor=tutor,
                           format_labels=tutors.FORMAT_LABELS,
                           rating=rating, feedback_items=feedback_items)