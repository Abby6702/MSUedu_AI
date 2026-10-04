"""Public pages: homepage, about/privacy, and health checks."""
from flask import Blueprint, abort, current_app, jsonify, render_template
from app.db import check_database

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    show_status = current_app.config["SHOW_SYSTEM_STATUS"]
    db_ok, db_message = (None, None)
    if show_status:
        db_ok, db_message = check_database()
    return render_template(
        "index.html", show_status=show_status, db_ok=db_ok, db_message=db_message
    )


@main_bp.route("/about")
def about():
    return render_template("about.html")


@main_bp.route("/healthz")
def healthz():
    """For hosting platforms and uptime monitors. It touches no database and reveals nothing."""
    return jsonify({"status": "ok"})


@main_bp.route("/health")
def health():
    """Development helper: also reports the database. Switched off in production."""
    if not current_app.config["SHOW_SYSTEM_STATUS"]:
        abort(404)
    db_ok, _ = check_database()
    body = {"status": "ok", "database": "up" if db_ok else "down"}
    return jsonify(body), (200 if db_ok else 503)