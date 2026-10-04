"""The live session page (students and tutors of a confirmed booking)."""
from flask import Blueprint, abort, current_app, g, render_template, url_for
from app.auth_utils import role_required
from app.services import file_service as fs
from app.services import live_logic, request_service as rs
from app.timeutil import utcnow

live_bp = Blueprint("live", __name__)


@live_bp.route("/sessions/<int:request_id>")
@role_required("student", "tutor")
def room(request_id):
    req = rs.get_for_user(request_id, g.user["id"])
    if req is None:
        abort(404)                                  # not your booking, or it does not exist
    state, message = live_logic.join_state(req["status"], req["start_at"], req["end_at"], utcnow())
    back = url_for("bookings.my_requests" if g.user["role"] == "student" else "bookings.tutor_requests")
    files = []
    if state != "open" and req["status"] in ("accepted", "completed"):
        try:
            files = fs.list_files(request_id)       # the room is shut, but the files can still be fetched
        except Exception:
            current_app.logger.exception("Could not list session files")
    return render_template("live/session.html", req=req, state=state, message=message,
                           back=back, files=files)