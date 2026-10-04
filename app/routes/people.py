"""Tutor profile details and photo, 'My students', and the student's sharing choice."""
from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)
from app import validators_people as vpp
from app.auth_utils import login_required, role_required
from app.services import people_service, photo_service
from app.services import user_service

people_bp = Blueprint("people", __name__)


def _audit(action, target_id):
    try:
        user_service.log_audit(g.user["id"], action, "user", target_id)
    except Exception:
        current_app.logger.exception("Could not write the audit log")


# ---------- tutor: details and photo ----------
@people_bp.route("/tutor/profile-details", methods=["GET", "POST"])
@role_required("tutor")
def details():
    errors = []
    current = people_service.get_details(g.user["id"]) or {}
    if request.method == "POST":
        data, errors = vpp.validate_details(request.form)
        if not errors:
            try:
                people_service.save_details(g.user["id"], data)
                flash("Profile details saved.", "success")
                return redirect(url_for("people.details"))
            except Exception:
                current_app.logger.exception("Saving tutor details failed")
                errors.append("Could not save your details. Please try again.")
    else:
        data = {"skills": current.get("skills") or "", "education": current.get("education") or "",
                "experience": current.get("experience") or ""}
    return render_template("people/details.html", data=data, errors=errors,
                           has_photo=bool(current.get("photo_filename")))


@people_bp.route("/tutor/profile-photo", methods=["POST"])
@role_required("tutor")
def upload_photo():
    file = request.files.get("photo")
    data = file.read(photo_service.MAX_BYTES + 1) if file else b""      # never read more than the limit
    try:
        photo_service.save_photo(g.user["id"], photo_service.process_image(data))
    except photo_service.PhotoError as error:
        flash(str(error), "error")
    except Exception:
        current_app.logger.exception("Saving a profile photo failed")
        flash("Could not save the photo. Please try again.", "error")
    else:
        flash("Photo saved.", "success")
    return redirect(url_for("people.details"))


@people_bp.route("/tutor/profile-photo/remove", methods=["POST"])
@role_required("tutor")
def remove_photo():
    try:
        photo_service.remove_photo(g.user["id"])
        flash("Photo removed.", "success")
    except Exception:
        current_app.logger.exception("Removing a profile photo failed")
        flash("Could not remove the photo. Please try again.", "error")
    return redirect(url_for("people.details"))


# ---------- serving a photo (permission checked on every request) ----------
@people_bp.route("/media/tutors/<int:tutor_id>/photo")
@login_required
def photo(tutor_id):
    info = people_service.photo_info(tutor_id)
    name = info["photo_filename"] if info else None
    if not name or not photo_service.NAME_RE.match(name):
        abort(404)
    if not people_service.can_view_photo(g.user["role"], g.user["id"], tutor_id,
                                         info["approval_status"], info["is_active"]):
        abort(404)                                  # looks the same as "no photo"
    return send_from_directory(str(photo_service.photo_dir()), name, mimetype="image/jpeg")


# ---------- tutor: My students ----------
@people_bp.route("/tutor/students")
@role_required("tutor")
def students():
    rows, error = [], None
    try:
        rows = people_service.list_students(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load students")
        error = "Could not load your students. Please try again."
    return render_template("people/students.html", rows=rows, error=error)


@people_bp.route("/tutor/students/<int:student_id>")
@role_required("tutor")
def student_detail(student_id):
    student = people_service.get_student(g.user["id"], student_id)
    if student is None:
        abort(404)                                  # not your student, or does not exist
    sessions, summary, summary_error = [], None, False
    try:
        sessions = people_service.student_sessions(g.user["id"], student_id)
    except Exception:
        current_app.logger.exception("Could not load student sessions")
    if student["shared"]:                           # only with the student's consent
        try:
            summary = people_service.shared_summary(student_id)
        except Exception:
            current_app.logger.exception("Could not load the shared summary")
            summary_error = True
    return render_template("people/student_detail.html", student=student, sessions=sessions,
                           summary=summary, summary_error=summary_error)


# ---------- student: the sharing choice ----------
@people_bp.route("/student/sharing", methods=["GET", "POST"])
@role_required("student")
def sharing():
    if request.method == "POST":
        enabled = request.form.get("share") == "on"
        try:
            people_service.set_sharing(g.user["id"], enabled)
            _audit("sharing_enabled" if enabled else "sharing_disabled", g.user["id"])
            flash("Sharing is now " + ("on." if enabled else "off."), "success")
        except Exception:
            current_app.logger.exception("Saving the sharing choice failed")
            flash("Could not save your choice. Please try again.", "error")
        return redirect(url_for("people.sharing"))
    try:
        enabled = people_service.get_sharing(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load the sharing choice")
        enabled = False
    return render_template("people/sharing.html", enabled=enabled)