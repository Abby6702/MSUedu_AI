"""Learning paths, lessons, the learning profile and recommendations (students only)."""
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, url_for)
from app.auth_utils import role_required
from app.services import learning_service as ls
from app.services import profile_service, recommendation_service

learning_bp = Blueprint("learning", __name__, url_prefix="/student/learning")


@learning_bp.route("/")
@role_required("student")
def index():
    subjects, stats, error = [], {"completed": 0, "streak": 0}, None
    try:
        subjects = ls.list_learning_subjects(g.user["id"])
        stats = ls.overall_stats(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load learning paths")
        error = "Could not load your learning paths. Please try again."
    return render_template("learning/index.html", subjects=subjects, stats=stats, error=error)


@learning_bp.route("/profile")
@role_required("student")
def profile():
    data, error = None, None
    try:
        data = profile_service.build_profile(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not build the learning profile")
        error = "Could not load your learning profile. Please try again."
    return render_template("learning/profile.html", p=data, error=error)


@learning_bp.route("/recommendations")
@role_required("student")
def recommendations():
    recommendation_service.safe_run(g.user["id"])          # refresh from the latest results
    recs, error = [], None
    try:
        recs = recommendation_service.list_active(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load recommendations")
        error = "Could not load your recommendations. Please try again."
    return render_template("learning/recommendations.html", recs=recs, error=error)


@learning_bp.route("/recommendations/<int:rec_id>/dismiss", methods=["POST"])
@role_required("student")
def dismiss_recommendation(rec_id):
    try:
        changed = recommendation_service.dismiss(rec_id, g.user["id"])
    except Exception:
        current_app.logger.exception("Could not dismiss a recommendation")
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for("learning.recommendations"))
    flash("Recommendation hidden. It returns only if your results change." if changed
          else "That recommendation was not found.", "success" if changed else "error")
    return redirect(url_for("learning.recommendations"))


@learning_bp.route("/<int:subject_id>")
@role_required("student")
def path(subject_id):
    subject = ls.get_subject(subject_id)
    if subject is None:
        abort(404)
    learning_path, error = ls.build_path([]), None
    try:
        learning_path = ls.build_path(ls.path_rows(g.user["id"], subject_id))
    except Exception:
        current_app.logger.exception("Could not load a learning path")
        error = "Could not load this learning path. Please try again."
    return render_template("learning/path.html", subject=subject, lp=learning_path, error=error)


@learning_bp.route("/lessons/<int:lesson_id>")
@role_required("student")
def lesson(lesson_id):
    item = ls.get_lesson(lesson_id, g.user["id"])
    if item is None:
        abort(404)
    return render_template("learning/lesson.html", lesson=item)


@learning_bp.route("/lessons/<int:lesson_id>/complete", methods=["POST"])
@role_required("student")
def complete(lesson_id):
    item = ls.get_lesson(lesson_id, g.user["id"])
    if item is None:
        abort(404)
    try:
        is_new = ls.mark_complete(g.user["id"], lesson_id)
    except Exception:
        current_app.logger.exception("Could not save lesson progress")
        flash("Could not save your progress. Please try again.", "error")
        return redirect(url_for("learning.lesson", lesson_id=lesson_id))
    if is_new:
        recommendation_service.safe_run(g.user["id"])       # the agent re-checks after new activity
    flash("Lesson marked as complete." if is_new else "You already completed this lesson.",
          "success" if is_new else "info")
    return redirect(url_for("learning.path", subject_id=item["subject_id"]))