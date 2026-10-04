"""Real-time events (Socket.IO): the room of a confirmed session, text chat, the setup
("signalling") messages WebRTC needs, and the shared whiteboard. The video and audio themselves go
directly between the two browsers and never pass through this server."""
import threading
from collections import deque

from flask import current_app, request, session
from flask_socketio import disconnect, emit, join_room

from app.services import live_logic, request_service, user_service
from app.services import session_chat_service as chat
from app.services import whiteboard_logic as wb
from app.timeutil import format_local, utcnow

_rooms = {}                      # socket id -> who is in which room
_boards = {}                     # request id -> {"board": Board, "deadline": datetime}
_lock = threading.Lock()


def _current_user():
    """Who is behind this socket? Same checks as a normal page: account active, session current."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    user = user_service.get_user_by_id(user_id)
    if (user is None or not user["is_active"] or user.get("must_change_password")
            or user.get("session_version", 0) != session.get("sv", 0)):
        return None
    return user


def _room(request_id):
    return f"session:{request_id}"


def _others(request_id, sid):
    return [s for s, info in _rooms.items() if info["request_id"] == request_id and s != sid]


def _format(row):
    return {"name": row["name"], "role": row["role"], "text": row["body"], "at": format_local(row["created_at"])}


def _member():
    """This socket's room info, or None (after telling the browser why)."""
    info = _rooms.get(request.sid)
    if info is None:
        return None
    if utcnow() > info["deadline"]:
        emit("error_msg", {"error": "This session's room has closed."})
        return None
    return info


def _purge_boards():
    """Forget the boards of rooms that have closed and are empty. Call with _lock held."""
    now = utcnow()
    in_use = {info["request_id"] for info in _rooms.values()}
    for request_id in [r for r, entry in _boards.items() if entry["deadline"] < now and r not in in_use]:
        _boards.pop(request_id, None)


def _board_command(action):
    """Run undo, redo or clear on this room's board. Returns (info, result)."""
    info = _member()
    if info is None or not live_logic.allow(info["cmd_hits"], 60, 60):
        return None, None
    with _lock:
        entry = _boards.get(info["request_id"])
        result = getattr(entry["board"], action)(info["role"]) if entry else None
    return info, result


def register_events(socketio):
    @socketio.on("connect")
    def on_connect(auth=None):
        if _current_user() is None:
            return False                                   # refuse: not logged in

    @socketio.on("join")
    def on_join(data):
        sid = request.sid
        try:
            user = _current_user()
        except Exception:
            current_app.logger.exception("Could not check the user for a live session")
            return emit("error_msg", {"error": "Something went wrong. Please reload the page."})
        if user is None or user["role"] not in ("student", "tutor"):
            return emit("error_msg", {"error": "Please log in again."})
        request_id = data.get("request_id") if isinstance(data, dict) else None
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 1:
            return emit("error_msg", {"error": "Session not found."})
        try:
            req = request_service.get_for_user(request_id, user["id"])
        except Exception:
            current_app.logger.exception("Could not load a session for the live room")
            return emit("error_msg", {"error": "Something went wrong. Please reload the page."})
        if req is None:
            return emit("error_msg", {"error": "Session not found."})
        state, message = live_logic.join_state(req["status"], req["start_at"], req["end_at"], utcnow())
        if state != "open":
            return emit("error_msg", {"error": message})

        role = "tutor" if user["id"] == req["tutor_id"] else "student"
        deadline = live_logic.room_deadline(req["end_at"])
        replaced_sids = []
        with _lock:
            _purge_boards()
            for old_sid, info in list(_rooms.items()):      # the same person in another tab
                if info["request_id"] == request_id and info["user_id"] == user["id"] and old_sid != sid:
                    _rooms.pop(old_sid, None)
                    replaced_sids.append(old_sid)
            others = _others(request_id, sid)
            _rooms[sid] = {"user_id": user["id"], "request_id": request_id, "role": role,
                           "name": user["full_name"], "deadline": deadline,
                           "chat_hits": deque(), "signal_hits": deque(),
                           "wb_hits": deque(), "cmd_hits": deque()}
            entry = _boards.setdefault(request_id, {"board": wb.Board(), "deadline": deadline})
            entry["deadline"] = deadline
            board_ops = entry["board"].snapshot()
        for old_sid in replaced_sids:
            emit("replaced", {}, to=old_sid)
            disconnect(old_sid)
        join_room(_room(request_id))

        try:
            history = [_format(r) for r in chat.recent(request_id, 100)]
        except Exception:
            current_app.logger.exception("Could not load the session chat")
            history = []
        emit("joined", {"role": role, "name": user["full_name"], "peer_present": bool(others),
                        "ice_servers": live_logic.build_ice_servers(current_app.config),
                        "messages": history})
        emit("wb_state", {"ops": board_ops})                # whoever joins late sees the board so far
        for other in others:                                # the person already there makes the offer
            emit("peer_joined", {"name": user["full_name"], "role": role}, to=other)

    @socketio.on("signal")
    def on_signal(data):
        info = _member()
        if info is None or not live_logic.allow(info["signal_hits"], 300, 60):
            return
        clean = live_logic.validate_signal(data)
        if clean is None:
            return
        for other in _others(info["request_id"], request.sid):
            emit("signal", clean, to=other)

    @socketio.on("chat")
    def on_chat(data):
        info = _member()
        if info is None:
            return
        if not live_logic.allow(info["chat_hits"], 6, 10):
            return emit("error_msg", {"error": "You are sending messages too quickly. Please wait a moment."})
        text = live_logic.clean_chat(data.get("text") if isinstance(data, dict) else None)
        if text is None:
            return emit("error_msg", {"error": "Type a message first (up to 1000 characters)."})
        try:
            if chat.count(info["request_id"]) >= chat.MAX_MESSAGES:
                return emit("error_msg", {"error": "This session's chat is full."})
            chat.add_message(info["request_id"], info["user_id"], text)
        except Exception:
            current_app.logger.exception("Could not save a session chat message")
            return emit("error_msg", {"error": "Your message could not be sent. Please try again."})
        emit("chat", {"name": info["name"], "role": info["role"], "text": text,
                      "at": format_local(utcnow())}, to=_room(info["request_id"]))

    # ---------- whiteboard ----------
    @socketio.on("wb_draw")
    def on_wb_draw(data):
        info = _member()
        if info is None or not live_logic.allow(info["wb_hits"], 1500, 60):
            return
        op = wb.clean_draw(data)
        if op is None:
            return
        with _lock:
            entry = _boards.get(info["request_id"])
            relay = entry["board"].draw(info["role"], op) if entry else None
        if relay is None:
            return
        for other in _others(info["request_id"], request.sid):
            emit("wb_draw", relay, to=other)

    @socketio.on("wb_undo")
    def on_wb_undo(*args):
        info, removed = _board_command("undo")
        if removed:
            emit("wb_remove", {"id": removed}, to=_room(info["request_id"]))

    @socketio.on("wb_redo")
    def on_wb_redo(*args):
        info, restored = _board_command("redo")
        if restored:
            emit("wb_add", restored, to=_room(info["request_id"]))

    @socketio.on("wb_clear")
    def on_wb_clear(*args):
        info, cleared = _board_command("clear")
        if cleared:
            emit("wb_clear", {}, to=_room(info["request_id"]))

    @socketio.on("disconnect")
    def on_disconnect(*args):
        with _lock:
            info = _rooms.pop(request.sid, None)
        if info:
            emit("peer_left", {"name": info["name"]}, to=_room(info["request_id"]))