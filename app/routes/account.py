"""Pages every logged-in user has: dashboard redirect, profile, change password."""
from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash
from app import validators
from app.auth_utils import login_required
from app.services import login_guard
from app.services import user_service as users

account_bp = Blueprint("account", __name__)

DASHBOARDS = {
    "student": "student.dashboard",
    "tutor": "tutor.dashboard",
    "admin": "admin.dashboard",
}


@account_bp.route("/dashboard")
@login_required
def dashboard():
    return redirect(url_for(DASHBOARDS[g.user["role"]]))


@account_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    role = g.user["role"]
    current = users.get_profile(g.user["id"], role) or {}
    errors = []

    if request.method == "POST":
        data, errors = validators.validate_profile(request.form, role)
        if not errors:
            try:
                users.update_profile(g.user["id"], role, data)
                flash("Profile saved.", "success")
                return redirect(url_for("account.profile"))
            except Exception:
                current_app.logger.exception("Profile update failed")
                errors.append("Could not save your profile. Please try again.")
    else:
        data = {"full_name": g.user["full_name"], **current}

    return render_template("account/profile.html", data=data, errors=errors, current=current)


@account_bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    forced = bool(g.user.get("must_change_password"))
    errors = []

    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        ident, ip = f"pwchange:{g.user['id']}", request.remote_addr or ""

        if login_guard.is_locked(ident, ip):
            errors.append(login_guard.LOCKED_MESSAGE)
        else:
            try:
                stored = users.get_password_hash(g.user["id"])
            except Exception:
                current_app.logger.exception("Could not read the password hash")
                stored, errors = None, ["The service is temporarily unavailable. Please try again."]

            if not errors:
                if not stored or not check_password_hash(stored, current):
                    login_guard.record_failure(ident, ip)
                    errors.append("Your current password is incorrect.")
                else:
                    errors += validators.password_errors(new)
                    if new != confirm:
                        errors.append("The two new passwords do not match.")
                    if not errors and new == current:
                        errors.append("Choose a password that is different from the current one.")

            if not errors:
                try:
                    session["sv"] = users.set_password(g.user["id"], new)   # this session stays valid
                    login_guard.clear(ident)
                    try:
                        users.log_audit(g.user["id"], "password_changed", "user", g.user["id"])
                    except Exception:
                        current_app.logger.exception("Could not write the audit log")
                    flash("Password changed. Other devices have been logged out.", "success")
                    return redirect(url_for("account.dashboard"))
                except Exception:
                    current_app.logger.exception("Changing the password failed")
                    errors.append("Could not change your password. Please try again.")

    return render_template("account/change_password.html", errors=errors, forced=forced)