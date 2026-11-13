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
    errors, request_errors, request_data = [], [], {}

    if request.method == "POST":
        fmt, selections, errors = vt.validate_teaching_setup(request.form, valid_ids)
        rates, rate_errors = vt.validate_subject_rates(
            request.form, [subject_id for subject_id, _topics in selections])
        payment, payment_errors = vt.validate_payment_details(request.form)
        errors.extend(rate_errors)
        errors.extend(payment_errors)
        if not errors:
            try:
                tutors.save_teaching_setup(g.user["id"], fmt, selections, rates, payment)
                flash("Subjects and format saved.", "success")
                return redirect(url_for("tutor.subjects"))
            except Exception:
                current_app.logger.exception("Saving tutor subjects failed")
                errors.append("Could not save. Please try again.")
        chosen = {sid: topics for sid, topics in selections}
        chosen_rates = rates
    else:
        fmt = tutors.get_format(g.user["id"])
        existing = tutors.get_tutor_subjects(g.user["id"])
        chosen = {r["subject_id"]: r["topics"] or "" for r in existing}
        chosen_rates = {
            r["subject_id"]: {duration: r[f"rate_{duration}"] or "" for duration in vt.RATE_DURATIONS}
            for r in existing
        }
        profile = users.get_profile(g.user["id"], "tutor") or {}
        payment = {
            "method": profile.get("payment_method", ""),
            "account_name": profile.get("payment_account_name", ""),
            "account_number": profile.get("payment_account_number", ""),
        }

    return render_template("tutor/subjects.html", all_subjects=all_subjects,
                           chosen=chosen, chosen_rates=chosen_rates, payment=payment,
                           rate_durations=vt.RATE_DURATIONS, payment_methods=vt.PAYMENT_METHODS,
                           fmt=fmt, errors=errors, request_errors=request_errors,
                           request_data=request_data,
                           subject_requests=subject_service.tutor_subject_requests(g.user["id"]))


@tutor_bp.route("/subjects/request", methods=["POST"])
@role_required("tutor")
def request_subject():
    data, errors = vt.validate_new_subject_request(request.form)
    if not errors:
        try:
            request_id = subject_service.create_tutor_subject_request(g.user["id"], data)
            if request_id:
                flash("Subject request sent to the administrator for approval.", "success")
            else:
                errors.append("That subject already exists or you already have a pending request for it.")
        except subject_service.SubjectExists:
            errors.append("That subject already exists or you already have a pending request for it.")
        except Exception:
            current_app.logger.exception("Submitting tutor subject request failed")
            errors.append("Could not submit the subject request. Please try again.")
    if errors:
        all_subjects = subject_service.list_subjects()
        existing = tutors.get_tutor_subjects(g.user["id"])
        profile = users.get_profile(g.user["id"], "tutor") or {}
        return render_template(
            "tutor/subjects.html", all_subjects=all_subjects,
            chosen={r["subject_id"]: r["topics"] or "" for r in existing},
            chosen_rates={r["subject_id"]: {
                duration: r[f"rate_{duration}"] or "" for duration in vt.RATE_DURATIONS
            } for r in existing},
            payment={"method": profile.get("payment_method", ""),
                     "account_name": profile.get("payment_account_name", ""),
                     "account_number": profile.get("payment_account_number", "")},
            rate_durations=vt.RATE_DURATIONS, payment_methods=vt.PAYMENT_METHODS,
            fmt=tutors.get_format(g.user["id"]), errors=[], request_errors=errors,
            request_data=request.form,
            subject_requests=subject_service.tutor_subject_requests(g.user["id"]),
        )
    return redirect(url_for("tutor.subjects"))


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