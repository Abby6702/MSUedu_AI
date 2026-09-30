"""Public pages: homepage, about/privacy, and a simple health check."""
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


@main_bp.route("/health")
def health():
    """Returns JSON so you can see how the backend answers requests."""
    if not current_app.config["SHOW_SYSTEM_STATUS"]:
        abort(404)
    db_ok, _ = check_database()
    body = {"status": "ok", "database": "up" if db_ok else "down"}
    return jsonify(body), (200 if db_ok else 503)