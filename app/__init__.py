"""Creates and configures the Flask application (the 'app factory')."""
import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from config import Config

csrf = CSRFProtect()

# Pages a person may still use while they are forced to choose a new password.
FORCED_CHANGE_ALLOWED = {"account.change_password", "auth.logout", "static"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; object-src 'none'")


def create_app(config_class=Config):
    app = Flask(__name__)
    from app.upload_limits import AppRequest
    app.request_class = AppRequest          # lets the file upload route accept bigger requests
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY is missing. Create a .env file (see .env.example) "
            "and set SECRET_KEY."
        )

    csrf.init_app(app)

       # Real-time layer (chat and WebRTC signalling). Threading mode works well on Windows.
    from app.extensions import socketio
    from app.sockets import register_events
    from app.deploy_checks import parse_origins
    socketio.init_app(app, async_mode="threading", max_http_buffer_size=200_000,
                         cors_allowed_origins=parse_origins(app.config.get("SOCKETIO_ORIGINS")))
    register_events(socketio)

    from app.services import notification_service, settings_service, user_service

    # ---- Runs before every request: who is logged in? ----
    @app.before_request
    def reject_oversized_request():
        limit = request.max_content_length
        if limit is not None and request.content_length is not None and request.content_length > limit:
            abort(413)

    @app.before_request
    def load_current_user():
        g.user = None
        user_id = session.get("user_id")
        if user_id is None:
            return
        try:
            user = user_service.get_user_by_id(user_id)
        except Exception:
            app.logger.exception("Could not load the logged-in user")
            return
        # A changed session_version means the password was changed or reset, or the
        # account was deactivated: this old session is no longer valid.
        if (user is None or not user["is_active"]
                or user.get("session_version", 0) != session.get("sv", 0)):
            session.clear()
            return
        g.user = user
        if user.get("must_change_password") and request.endpoint not in FORCED_CHANGE_ALLOWED:
            flash("Please choose a new password to continue.", "info")
            return redirect(url_for("account.change_password"))

    # ---- Runs when a page is drawn: announcement banner and unread badge ----
    @app.context_processor
    def inject_globals():
        count, note = 0, ""
        # Skipped in automated tests (TESTING) so page tests never need a database.
        if not app.config.get("TESTING"):
            note = settings_service.announcement()       # handles its own errors
            if g.get("user"):
                try:
                    count = notification_service.unread_count(g.user["id"])
                except Exception:
                    app.logger.exception("Could not count notifications")
        return {"unread_count": count, "announcement": note}

    # ---- Runs after every request: safer response headers ----
    @app.after_request
    def add_security_headers(response):
        if g.get("user"):
            # Stops the browser "Back" button from showing private pages after logout
            response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy",
                                       "camera=(self), microphone=(self), display-capture=(self), geolocation=()")
        if app.config.get("CSP_ENABLED"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if app.config.get("SESSION_COOKIE_SECURE"):          # only meaningful over HTTPS
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # ---- Friendly error pages (they never show technical details) ----
    def show_error(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(403)
    def forbidden(_e):
        return show_error(403, "Access denied", "You do not have permission to view this page.")

    @app.errorhandler(404)
    def not_found(_e):
        return show_error(404, "Page not found", "That page does not exist.")

    @app.errorhandler(405)
    def wrong_method(_e):
        return show_error(405, "Method not allowed", "That page cannot be opened this way.")

    @app.errorhandler(413)
    def too_large(_e):
        return show_error(413, "Request too large", "What you sent was too large. Please send less data.")

    @app.errorhandler(500)
    def server_error(_e):
        return show_error(500, "Something went wrong",
                          "An unexpected error happened on our side. Please try again in a moment.")

    @app.errorhandler(CSRFError)
    def csrf_failed(_e):
        return show_error(400, "Form expired",
                          "Your form is no longer valid. Go back, refresh the page and try again.")

    # ---- Register route groups (blueprints) ----
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.account import account_bp
    from app.routes.student import student_bp
    from app.routes.tutor import tutor_bp
    from app.routes.admin import admin_bp
    from app.routes.bookings import bookings_bp
    from app.routes.assistant import assistant_bp
    from app.routes.quizzes import quizzes_bp
    from app.routes.agent import agent_bp
    from app.routes.notifications import notifications_bp
    from app.routes.progress import progress_bp
    from app.routes.learning import learning_bp
    from app.routes.people import people_bp
    from app.routes.live import live_bp
    from app.routes.session_ai import session_ai_bp
    from app.routes.session_files import session_files_bp
    from app.routes.content import content_bp
    for bp in (main_bp, auth_bp, account_bp, student_bp, tutor_bp, admin_bp,
               bookings_bp, assistant_bp, quizzes_bp, agent_bp,
               notifications_bp, progress_bp, learning_bp, people_bp, live_bp, session_ai_bp, session_files_bp, content_bp):
        app.register_blueprint(bp)

    # ---- Terminal command:  flask --app run create-admin ----
    @app.cli.command("create-admin")
    def create_admin():
        """Create an administrator account (password is typed hidden)."""
        from app import validators

        full_name = validators.clean(click.prompt("Full name"))
        email = click.prompt("Email").strip().lower()
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)

        problems = []
        if not 2 <= len(full_name) <= 100:
            problems.append("Name must be 2-100 characters.")
        problems += [p for p in [validators.email_error(email)] if p]
        problems += validators.password_errors(password)
        if problems:
            for p in problems:
                click.echo(f"  - {p}")
            raise SystemExit(1)

        try:
            new_id = user_service.create_user(full_name, email, password, "admin")
        except user_service.EmailAlreadyUsed:
            click.echo("That email is already registered.")
            raise SystemExit(1)
        user_service.log_audit(None, "admin_created", "user", new_id, "Created from command line")
        click.echo(f"Administrator created (id {new_id}). You can log in now.")

    # ---- Terminal command:  flask --app run send-reminders ----
    @app.cli.command("send-reminders")
    def send_reminders():
        """Send any due session reminders once (handy with Windows Task Scheduler)."""
        hours = notification_service.parse_hours(app.config["REMINDER_HOURS"])
        click.echo(f"New reminders sent: {notification_service.send_due_reminders(hours)}")

    return app