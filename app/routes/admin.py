"""Administrator pages. Every route needs the admin role, and important actions are audited."""
import math
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)
from werkzeug.security import generate_password_hash
from app import security
from app import validators_admin as va
from app import validators_tutor as vt
from app.auth_utils import role_required
from app.services import admin_service, analytics_service, settings_service, subject_service
from app.services import tutor_service as tutors
from app.services import user_service as users

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

USER_ACTIONS = {
    "deactivate": {"title": "Deactivate this account?", "button": "Yes, deactivate", "danger": True,
                   "text": "They will be logged out everywhere and cannot log in. A deactivated tutor "
                           "disappears from search. Existing requests and sessions are not changed "
                           "automatically. You can reactivate the account later."},
    "activate": {"title": "Reactivate this account?", "button": "Yes, reactivate", "danger": False,
                 "text": "They will be able to log in again."},
    "reset_password": {"title": "Reset this person's password?", "button": "Yes, reset the password",
                       "danger": True,
                       "text": "A random temporary password will be shown to YOU once. Give it to the "
                               "person privately, after checking who they are. They must choose a new "
                               "password at their next login, and all their current sessions end now."},
}


def _audit(action, target_type=None, target_id=None, details=None):
    """The action is already done, so an audit failure is logged instead of hiding the success."""
    try:
        users.log_audit(g.user["id"], action, target_type, target_id, details)
    except Exception:
        current_app.logger.exception("Could not write the audit log")


def _pager(endpoint, page, total, **params):
    pages = max(1, math.ceil(total / admin_service.PAGE_SIZE))

    def link(number):
        return url_for(endpoint, page=number, **{k: v for k, v in params.items() if v not in ("", None)})
    return {"page": page, "pages": pages, "total": total,
            "prev": link(page - 1) if page > 1 else None,
            "next": link(page + 1) if page < pages else None}


# ---------- overview and reports ----------
@admin_bp.route("/dashboard")
@role_required("admin")
def dashboard():
    stats = activity = subjects = None
    try:
           stats = admin_service.overview()
    except Exception:
           current_app.logger.exception("Could not load the overview")
    try:                                   # the charts failing must not hide the numbers
           activity = analytics_service.activity()
           subjects = analytics_service.subject_charts()
    except Exception:
           current_app.logger.exception("Could not load the dashboard charts")
           activity = subjects = None
    return render_template("admin/dashboard.html", stats=stats, activity=activity, subjects=subjects)


@admin_bp.route("/reports")
@role_required("admin")
def reports():
    data = None
    try:
        data = admin_service.reports()
    except Exception:
        current_app.logger.exception("Could not build the reports")
    return render_template("admin/reports.html", data=data)


# ---------- users ----------
@admin_bp.route("/users")
@role_required("admin")
def user_list():
    filters, page = va.parse_user_filters(request.args), va.parse_page(request.args)
    rows, total, error = [], 0, None
    try:
        rows, total, page = admin_service.list_users(filters, page)
    except Exception:
        current_app.logger.exception("Could not list users")
        error = "Could not load accounts. Please try again."
    return render_template("admin/users.html", rows=rows, filters=filters, error=error,
                           pager=_pager("admin.user_list", page, total, **filters))


@admin_bp.route("/users/<int:user_id>/<any(activate,deactivate,reset_password):action>",
                methods=["GET", "POST"])
@role_required("admin")
def user_action(user_id, action):
    target = admin_service.get_manageable_user(user_id)
    if target is None:
        abort(404)                    # missing, or an administrator account
    if (action == "deactivate" and not target["is_active"]) or \
       (action == "activate" and target["is_active"]):
        flash("That account is already in that state.", "info")
        return redirect(url_for("admin.user_list"))

    if request.method == "POST":
        try:
            if action == "reset_password":
                temp = security.generate_temp_password()
                admin_service.reset_password(user_id, generate_password_hash(temp))
                _audit("password_reset_by_admin", "user", user_id, target["role"])   # never the password
                return render_template("admin/password_result.html", target=target, temp_password=temp)
            admin_service.set_active(user_id, action == "activate")
            _audit("user_activated" if action == "activate" else "user_deactivated",
                   "user", user_id, target["role"])
            flash("Account " + ("reactivated." if action == "activate" else "deactivated."), "success")
        except Exception:
            current_app.logger.exception("Admin user action failed")
            flash("Something went wrong. Nothing was changed. Please try again.", "error")
        return redirect(url_for("admin.user_list"))

    return render_template("admin/user_confirm.html", target=target, action=action,
                           info=USER_ACTIONS[action], back_url=url_for("admin.user_list"))


# ---------- tutor review (Phase 3) ----------
@admin_bp.route("/tutors")
@role_required("admin")
def review_tutors():
    status = request.args.get("status", "pending")
    if status not in ("pending", "approved", "rejected"):
        status = "pending"
    return render_template("admin/tutors.html", status=status,
                           tutor_list=tutors.list_tutors_for_review(status),
                           format_labels=tutors.FORMAT_LABELS)


@admin_bp.route("/tutors/<int:tutor_id>/review", methods=["POST"])
@role_required("admin")
def review_action(tutor_id):
    decision = request.form.get("decision")
    if decision not in ("approved", "rejected"):
        flash("Unknown action.", "error")
        return redirect(url_for("admin.review_tutors"))
    try:
        problem = tutors.set_approval(tutor_id, decision, g.user["id"])
        if problem:
            flash(problem, "error")
        else:
            _audit(f"tutor_{decision}", "user", tutor_id)
            flash(f"Tutor profile {decision}.", "success")
    except Exception:
        current_app.logger.exception("Tutor review failed")
        flash("Could not save the decision. Please try again.", "error")
    return redirect(url_for("admin.review_tutors"))


# ---------- subjects (Phase 3) ----------
@admin_bp.route("/subjects", methods=["GET", "POST"])
@role_required("admin")
def subjects():
    errors, data = [], {}
    if request.method == "POST":
        data, errors = vt.validate_subject_form(request.form)
        if not errors:
            try:
                new_id = subject_service.create_subject(data["name"], data["category"])
                _audit("subject_created", "subject", new_id, data["name"])
                flash("Subject added.", "success")
                return redirect(url_for("admin.subjects"))
            except subject_service.SubjectExists:
                errors.append("A subject with that name already exists.")
            except Exception:
                current_app.logger.exception("Creating subject failed")
                errors.append("Could not save the subject. Please try again.")
    return render_template("admin/subjects.html", subject_list=subject_service.list_subjects(False),
                           errors=errors, data=data)


@admin_bp.route("/subjects/<int:subject_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_subject(subject_id):
    new_state = subject_service.toggle_subject(subject_id)
    if new_state is None:
        flash("Subject not found.", "error")
    else:
        _audit("subject_toggled", "subject", subject_id, "active" if new_state else "inactive")
        flash("Subject is now " + ("active." if new_state else "inactive."), "success")
    return redirect(url_for("admin.subjects"))


# ---------- monitoring ----------
@admin_bp.route("/requests")
@role_required("admin")
def request_list():
    status, page = va.parse_request_status(request.args), va.parse_page(request.args)
    rows, total, error = [], 0, None
    try:
        rows, total, page = admin_service.list_requests(status, page)
    except Exception:
        current_app.logger.exception("Could not list requests")
        error = "Could not load requests. Please try again."
    return render_template("admin/requests.html", rows=rows, status=status, error=error,
                           statuses=va.REQUEST_STATUSES,
                           pager=_pager("admin.request_list", page, total, status=status))


@admin_bp.route("/feedback")
@role_required("admin")
def feedback_list():
    show, page = va.parse_feedback_filter(request.args), va.parse_page(request.args)
    rows, total, error = [], 0, None
    try:
        rows, total, page = admin_service.list_feedback(show, page)
    except Exception:
        current_app.logger.exception("Could not list feedback")
        error = "Could not load feedback. Please try again."
    return render_template("admin/feedback.html", rows=rows, show=show, error=error,
                           pager=_pager("admin.feedback_list", page, total, show=show))


@admin_bp.route("/feedback/<int:feedback_id>/<any(hide,unhide):action>", methods=["POST"])
@role_required("admin")
def feedback_action(feedback_id, action):
    hide = action == "hide"
    try:
        changed = admin_service.set_feedback_hidden(feedback_id, hide)
    except Exception:
        current_app.logger.exception("Moderating feedback failed")
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for("admin.feedback_list"))
    if changed:
        _audit("feedback_hidden" if hide else "feedback_unhidden", "feedback", feedback_id)
        flash("Feedback " + ("hidden." if hide else "shown again."), "success")
    else:
        flash("That feedback was not found or is already in that state.", "error")
    return redirect(url_for("admin.feedback_list"))


@admin_bp.route("/audit")
@role_required("admin")
def audit_list():
    action, page = va.parse_audit_action(request.args), va.parse_page(request.args)
    rows, total, actions, error = [], 0, [], None
    try:
        rows, total, page = admin_service.list_audit(action, page)
        actions = admin_service.audit_actions()
    except Exception:
        current_app.logger.exception("Could not load the audit log")
        error = "Could not load the audit log. Please try again."
    return render_template("admin/audit.html", rows=rows, action=action, actions=actions, error=error,
                           pager=_pager("admin.audit_list", page, total, action=action))


# ---------- platform settings ----------
@admin_bp.route("/settings", methods=["GET", "POST"])
@role_required("admin")
def settings():
    errors = []
    if request.method == "POST":
        values, errors = va.validate_settings(request.form)
        if not errors:
            try:
                settings_service.save(g.user["id"], values)
                _audit("settings_changed", None, None,
                       f"registration_open={values['registration_open']}; "
                       f"announcement {'set' if values['announcement'] else 'cleared'}")
                flash("Settings saved.", "success")
                return redirect(url_for("admin.settings"))
            except Exception:
                current_app.logger.exception("Saving settings failed")
                errors.append("Could not save the settings. Please try again.")
        current = values
    else:
        current = settings_service.get_all()
    return render_template("admin/settings.html", current=current, errors=errors,
                           max_length=va.MAX_ANNOUNCEMENT)