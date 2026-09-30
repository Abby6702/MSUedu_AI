"""Register, log in, log out."""
from flask import (Blueprint, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash
from app import validators
from app.services import login_guard, settings_service
from app.services import user_service as users

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("account.dashboard"))
    if not settings_service.registration_open():
        return render_template("auth/registration_closed.html"), 403
    data, errors = {}, []

    if request.method == "POST":
        data, errors = validators.validate_registration(request.form)
        if not errors:
            try:
                users.create_user(data["full_name"], data["email"],
                                  request.form["password"], data["role"])
            except users.EmailAlreadyUsed:
                errors.append("That email is already registered. Try logging in instead.")
            except Exception:
                current_app.logger.exception("Registration failed")
                errors.append("Something went wrong on our side. Please try again.")
            else:
                flash("Account created. You can log in now.", "success")
                return redirect(url_for("auth.login"))

    return render_template("auth/register.html", data=data, errors=errors)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("account.dashboard"))
    errors, email = [], ""

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        ip = request.remote_addr or ""

        if login_guard.is_locked(email, ip):
            # Even a correct password is refused while locked, and we say nothing about the account.
            errors.append(login_guard.LOCKED_MESSAGE)
        else:
            user = None
            try:
                user = users.get_user_for_login(email)
            except Exception:
                current_app.logger.exception("Login lookup failed")
                errors.append("The service is temporarily unavailable. Please try again.")

            if not errors:
                if user and user["is_active"] and check_password_hash(user["password_hash"], password):
                    session.clear()              # fresh session (prevents session fixation)
                    session["user_id"] = user["id"]
                    session["sv"] = user["session_version"]
                    session.permanent = True
                    users.record_login(user["id"])
                    login_guard.clear(email)
                    return redirect(url_for("account.dashboard"))
                login_guard.record_failure(email, ip)   # counted even for unknown emails
                # Same message for "no such email", "wrong password" and "deactivated"
                errors.append("Incorrect email or password.")

    return render_template("auth/login.html", errors=errors, email=email)


@auth_bp.route("/logout", methods=["POST"])   # POST + CSRF so other sites can't log you out
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.home"))