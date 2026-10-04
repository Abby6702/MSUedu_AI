"""Files shared during a live session (students and tutors of that booking only)."""
from flask import Blueprint, current_app, g, jsonify, request, send_from_directory, url_for

from app.auth_utils import role_required
from app.extensions import socketio
from app.services import file_service as fs
from app.services import live_logic, request_service as rs
from app.timeutil import format_local, utcnow

session_files_bp = Blueprint("session_files", __name__)


def _error(message, status):
    return jsonify({"ok": False, "error": message}), status


def _booking(request_id):
    """The booking, only for its two people and only while it is confirmed or completed."""
    req = rs.get_for_user(request_id, g.user["id"])
    return req if req and req["status"] in ("accepted", "completed") else None


def _item(row, request_id):
    return {"id": row["id"], "name": row["original_name"], "size": row["size_label"],
            "kind": row["kind"], "uploader": row["uploader"], "role": row["role"],
            "at": format_local(row["created_at"]),
            "url": url_for("session_files.download", request_id=request_id, file_id=row["id"])}


def _broadcast(event, request_id, payload):
    """Tell everyone in the room. A failure here never breaks the upload or delete itself."""
    try:
        socketio.emit(event, payload, to=f"session:{request_id}")
    except Exception:
        current_app.logger.exception("Could not tell the room about a file change")


@session_files_bp.route("/sessions/<int:request_id>/files", methods=["GET"])
@role_required("student", "tutor")
def list_files(request_id):
    if _booking(request_id) is None:
        return _error("Session not found.", 404)
    try:
        rows = fs.list_files(request_id)
    except Exception:
        current_app.logger.exception("Could not list session files")
        return _error("The files could not be loaded. Please try again.", 500)
    return jsonify({"ok": True, "files": [_item(r, request_id) for r in rows]})


@session_files_bp.route("/sessions/<int:request_id>/files", methods=["POST"])
@role_required("student", "tutor")
def upload(request_id):
    req = _booking(request_id)
    if req is None:
        return _error("Session not found.", 404)
    state, _message = live_logic.join_state(req["status"], req["start_at"], req["end_at"], utcnow())
    if state != "open":
        return _error("Files can be shared only while the session room is open.", 403)

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return _error("Choose a file to upload.", 400)
    data = uploaded.read(fs.MAX_FILE_BYTES + 1)                # never read more than the limit
    try:
        row = fs.save_upload(request_id, g.user["id"], g.user["full_name"], g.user["role"],
                             uploaded.filename, data)
    except fs.FileError as error:
        return _error(str(error), 400)
    except Exception:
        current_app.logger.exception("Saving a session file failed")
        return _error("The file could not be saved. Please try again.", 500)
    item = _item(row, request_id)
    _broadcast("file_added", request_id, {"file": item})
    return jsonify({"ok": True, "file": item})


@session_files_bp.route("/sessions/<int:request_id>/files/<int:file_id>")
@role_required("student", "tutor")
def download(request_id, file_id):
    from flask import abort
    if _booking(request_id) is None:
        abort(404)
    row = fs.get_file(request_id, file_id)
    if row is None or not fs.NAME_RE.match(row["stored_name"]):
        abort(404)
    folder = fs.files_dir()
    if not (folder / row["stored_name"]).is_file():
        abort(404)
    return send_from_directory(str(folder), row["stored_name"], mimetype=fs.KINDS[row["kind"]][2],
                               as_attachment=True, download_name=row["original_name"])


@session_files_bp.route("/sessions/<int:request_id>/files/<int:file_id>/delete", methods=["POST"])
@role_required("student", "tutor")
def delete(request_id, file_id):
    if _booking(request_id) is None:
        return _error("Session not found.", 404)
    row = fs.get_file(request_id, file_id)
    if row is None:
        return _error("File not found.", 404)
    if row["user_id"] != g.user["id"]:
        return _error("You can only remove files you shared.", 403)
    try:
        fs.delete_row(file_id, request_id, g.user["id"])
        fs.delete_stored(row["stored_name"])
    except Exception:
        current_app.logger.exception("Removing a session file failed")
        return _error("The file could not be removed. Please try again.", 500)
    _broadcast("file_removed", request_id, {"id": file_id})
    return jsonify({"ok": True})