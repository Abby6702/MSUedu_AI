"""Notification history and settings. Every logged-in user has their own."""
from flask import (Blueprint, current_app, flash, g, redirect,
                   render_template, request, url_for)
from app.auth_utils import login_required
from app.services import notification_service as ns

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def _safe_link(link):
    """Only internal paths are allowed, so a notification can never send someone to another site."""
    if isinstance(link, str) and link.startswith("/") and not link.startswith("//"):
        return link
    return url_for("notifications.index")


@notifications_bp.route("/")
@login_required
def index():
    items, error = [], None
    try:
        items = ns.list_for_user(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load notifications")
        error = "Could not load your notifications. Please try again."
    return render_template("notifications/list.html", items=items, error=error)


@notifications_bp.route("/<int:notification_id>/open")
@login_required
def open_notification(notification_id):
    note = ns.get_own(notification_id, g.user["id"])
    if note is None:
        return redirect(url_for("notifications.index"))
    ns.mark_read(notification_id, g.user["id"])
    return redirect(_safe_link(note["link"]))


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def read(notification_id):
    ns.mark_read(notification_id, g.user["id"])
    return redirect(url_for("notifications.index"))


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    ns.mark_all_read(g.user["id"])
    flash("All notifications marked as read.", "success")
    return redirect(url_for("notifications.index"))


@notifications_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        try:
            ns.set_reminders_enabled(g.user["id"], request.form.get("reminders_enabled") == "on")
            flash("Settings saved.", "success")
        except Exception:
            current_app.logger.exception("Saving notification settings failed")
            flash("Could not save your settings. Please try again.", "error")
        return redirect(url_for("notifications.settings"))
    try:
        enabled = ns.reminders_enabled(g.user["id"])
    except Exception:
        current_app.logger.exception("Could not load notification settings")
        enabled = True
    return render_template("notifications/settings.html", enabled=enabled)