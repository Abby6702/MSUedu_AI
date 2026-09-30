from flask import (Blueprint, current_app, flash, g, redirect,
                   render_template, request, url_for)
from app import validators_tutor as vt
from app.auth_utils import role_required
from app.services import request_service as rs
from app.services import subject_service, tutor_service as tutors
from app.services import user_service as users

tutor_bp = Blueprint("tutor", __name__, url_prefix="/tutor")


@tutor_bp.route("/dashboard")
@role_required("tutor")
def dashboard():
    profile = users.get_profile(g.user["id"], "tutor") or {}
    summary = tutors.setup_summary(g.user["id"])
    incoming, upcoming = [], []
    try:
        groups = rs.grouped_requests(g.user["id"], "tutor")
        incoming = [r for r in groups["attention"] if r["status"] == "pending"][:3]
        upcoming = groups["upcoming"][:3]
    except Exception:
        current_app.logger.exception("Could not load dashboard data")
    return render_template("tutor/dashboard.html", profile=profile, summary=summary,
                           incoming=incoming, upcoming=upcoming)


@tutor_bp.route("/subjects", methods=["GET", "POST"])
@role_required("tutor")
def subjects():
    all_subjects = subject_service.list_subjects()
    valid_ids = {s["id"] for s in all_subjects}
    errors = []

    if request.method == "POST":
        fmt, selections, errors = vt.validate_teaching_setup(request.form, valid_ids)
        if not errors:
            try:
                tutors.save_teaching_setup(g.user["id"], fmt, selections)
                flash("Subjects and format saved.", "success")
                return redirect(url_for("tutor.subjects"))
            except Exception:
                current_app.logger.exception("Saving tutor subjects failed")
                errors.append("Could not save. Please try again.")
        chosen = {sid: topics for sid, topics in selections}
    else:
        fmt = tutors.get_format(g.user["id"])
        chosen = {r["subject_id"]: r["topics"] or ""
                  for r in tutors.get_tutor_subjects(g.user["id"])}

    return render_template("tutor/subjects.html", all_subjects=all_subjects,
                           chosen=chosen, fmt=fmt, errors=errors)


@tutor_bp.route("/availability", methods=["GET", "POST"])
@role_required("tutor")
def availability():
    errors = []
    if request.method == "POST":
        data, errors = vt.validate_slot(request.form)
        if not errors:
            try:
                problem = tutors.add_slot(g.user["id"], data["day"], data["start"], data["end"])
                if problem:
                    errors.append(problem)
                else:
                    flash("Availability slot added.", "success")
                    return redirect(url_for("tutor.availability"))
            except Exception:
                current_app.logger.exception("Adding slot failed")
                errors.append("Could not save the slot. Please try again.")

    return render_template("tutor/availability.html", slots=tutors.list_availability(g.user["id"]),
                           errors=errors, day_names=vt.DAY_NAMES)


@tutor_bp.route("/availability/<int:slot_id>/delete", methods=["POST"])
@role_required("tutor")
def delete_slot(slot_id):
    if tutors.delete_slot(g.user["id"], slot_id):
        flash("Slot removed.", "success")
    else:
        flash("That slot was not found.", "error")
    return redirect(url_for("tutor.availability"))