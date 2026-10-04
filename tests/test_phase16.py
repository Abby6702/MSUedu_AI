"""Run with:  python -m pytest -v
MySQL is faked. Socket.IO tests use its built-in test client (no browser, no real video)."""
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import create_app, sockets
from app.extensions import socketio
from app.services import live_logic as ll, request_service, user_service
from app.services import session_chat_service as chat
from app.timeutil import utcnow
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P16Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def app():
    return create_app(P16Config)


@pytest.fixture
def client(app):
    return app.test_client()


USERS = {1: {"id": 1, "full_name": "Sample Student", "email": "s@example.com", "role": "student", "is_active": 1},
         2: {"id": 2, "full_name": "Sample Tutor", "email": "t@example.com", "role": "tutor", "is_active": 1},
         3: {"id": 3, "full_name": "Other Student", "email": "o@example.com", "role": "student", "is_active": 1},
         4: {"id": 4, "full_name": "An Admin", "email": "a@example.com", "role": "admin", "is_active": 1}}


def T(**kw):
    return utcnow() + timedelta(**kw)


# ======================= pure rules =======================
START, END = datetime(2026, 10, 5, 6, 0), datetime(2026, 10, 5, 7, 0)


@pytest.mark.parametrize("status,now,expected", [
    ("accepted", START - timedelta(minutes=16), "early"), ("accepted", START - timedelta(minutes=15), "open"),
    ("accepted", START + timedelta(minutes=30), "open"), ("accepted", END + timedelta(minutes=60), "open"),
    ("accepted", END + timedelta(minutes=61), "ended"),
    ("pending", START, "unavailable"), ("cancelled", START, "unavailable"), ("completed", START, "unavailable")])
def test_join_window(status, now, expected):
    state, message = ll.join_state(status, START, END, now)
    assert state == expected and (message == "") == (expected == "open")


def test_ice_servers_include_turn_only_when_fully_configured():
    base = {"STUN_URLS": "stun:a.example:3478, bogus, stun:b.example:3478"}
    assert ll.build_ice_servers(base) == [{"urls": ["stun:a.example:3478", "stun:b.example:3478"]}]
    partial = dict(base, TURN_URLS="turn:t.example:3478", TURN_USERNAME="u")
    assert len(ll.build_ice_servers(partial)) == 1                              # no credential, no TURN
    full = dict(partial, TURN_CREDENTIAL="secret")
    assert ll.build_ice_servers(full)[1] == {"urls": ["turn:t.example:3478"], "username": "u", "credential": "secret"}
    assert ll.build_ice_servers({}) == [] and ll.build_ice_servers({"STUN_URLS": "http://evil.example"}) == []


SDP = "v=0\r\n" + "a=x" * 10


@pytest.mark.parametrize("payload", [
    None, "x", {}, {"type": "hack", "data": {}}, {"type": "offer", "data": "x"},
    {"type": "offer", "data": {"type": "answer", "sdp": SDP}},          # type must match
    {"type": "offer", "data": {"type": "offer", "sdp": "short"}},
    {"type": "offer", "data": {"type": "offer", "sdp": "x" * (ll.MAX_SDP + 1)}},
    {"type": "offer", "data": {"type": "offer", "sdp": 5}},
    {"type": "candidate", "data": {}}, {"type": "candidate", "data": {"candidate": "x" * 1001}}])
def test_bad_signals_are_rejected(payload):
    assert ll.validate_signal(payload) is None


def test_signals_are_rebuilt_with_known_fields_only():
    offer = ll.validate_signal({"type": "offer", "data": {"type": "offer", "sdp": SDP, "evil": "x"}, "extra": 1})
    assert offer == {"type": "offer", "data": {"type": "offer", "sdp": SDP}}
    cand = ll.validate_signal({"type": "candidate", "data": {
        "candidate": "candidate:1 1 udp 1 1.2.3.4 5 typ host", "sdpMid": "0", "sdpMLineIndex": 0,
        "usernameFragment": "abc", "evil": "x"}})
    assert set(cand["data"]) == {"candidate", "sdpMid", "sdpMLineIndex", "usernameFragment"}
    end_marker = ll.validate_signal({"type": "candidate", "data": {"candidate": "", "sdpMLineIndex": True}})
    assert end_marker["data"] == {"candidate": ""}                           # bool is not a number


def test_chat_cleaning():
    assert ll.clean_chat("  hello\x00 there\x7f ") == "hello there"
    assert ll.clean_chat("line1\nline2") == "line1\nline2"
    assert ll.clean_chat("") is None and ll.clean_chat("  \n ") is None and ll.clean_chat(5) is None
    assert ll.clean_chat("x" * 1001) is None and ll.clean_chat("x" * 1000) == "x" * 1000


def test_rate_limit():
    bucket = deque()
    assert [ll.allow(bucket, 3, 10, now=n) for n in (0, 1, 2, 3)] == [True, True, True, False]
    assert ll.allow(bucket, 3, 10, now=11) is True                           # the window moved on


# ======================= the page =======================
def login_as(client, monkeypatch, role="student", user_id=1):
    user = dict(USERS[1], id=user_id, role=role)
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def booking(**changes):
    base = {"id": 7, "student_id": 1, "tutor_id": 2, "status": "accepted", "topic": "<i>Loops</i>",
            "subject_name": "Python Programming", "student_name": "Sample Student",
            "tutor_name": "Sample Tutor", "start_at": T(minutes=-5), "end_at": T(minutes=55)}
    base.update(changes)
    return base


def test_the_page_is_for_students_and_tutors_of_the_booking(client, monkeypatch):
    assert client.get("/sessions/7").status_code == 302
    login_as(client, monkeypatch, "admin", 4)
    assert client.get("/sessions/7").status_code == 403
    login_as(client, monkeypatch, "student", 3)
    monkeypatch.setattr(request_service, "get_for_user", lambda rid, uid: None)
    assert client.get("/sessions/7").status_code == 404                    # someone else's booking


def test_an_open_room_loads_the_scripts_and_escapes_text(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(request_service, "get_for_user", lambda rid, uid: booking())
    page = client.get("/sessions/7")
    assert page.status_code == 200 and b"js/socket.io.min.js" in page.data and b"js/session.js" in page.data
    assert b"<i>Loops</i>" not in page.data and b"&lt;i&gt;Loops" in page.data
    assert b"not recorded" in page.data and b"wbCanvas" in page.data


@pytest.mark.parametrize("changes,fragment", [
    ({"start_at": T(hours=3), "end_at": T(hours=4)}, b"opens 15 minutes before"),
    ({"start_at": T(hours=-5), "end_at": T(hours=-4)}, b"has closed"),
    ({"status": "pending"}, b"not confirmed")])
def test_a_closed_room_shows_why_and_loads_no_scripts(client, monkeypatch, changes, fragment):
    from app.services import file_service
    monkeypatch.setattr(file_service, "list_files", lambda rid: [])
    login_as(client, monkeypatch)
    monkeypatch.setattr(request_service, "get_for_user", lambda rid, uid: booking(**changes))
    page = client.get("/sessions/7")
    assert page.status_code == 200 and fragment in page.data and b"session.js" not in page.data


# ======================= real-time events =======================
@pytest.fixture
def live(monkeypatch):
    env = {"req": booking(), "saved": [], "count": 0}
    sockets._rooms.clear()
    monkeypatch.setattr(user_service, "get_user_by_id", lambda uid: USERS.get(uid))
    monkeypatch.setattr(request_service, "get_for_user", lambda rid, uid: dict(env["req"]) if (
        rid == 7 and uid in (env["req"]["student_id"], env["req"]["tutor_id"])) else None)
    monkeypatch.setattr(chat, "recent", lambda rid, limit: [
        {"id": 1, "name": "Sample Tutor", "body": "<b>Welcome</b>", "role": "tutor",
         "created_at": datetime(2026, 10, 5, 6, 0)}])
    monkeypatch.setattr(chat, "count", lambda rid: env["count"])
    monkeypatch.setattr(chat, "add_message", lambda rid, uid, text: env["saved"].append((rid, uid, text)))
    yield env
    sockets._rooms.clear()


def connect(app, user_id):
    flask_client = app.test_client()
    with flask_client.session_transaction() as sess:
        sess["user_id"] = user_id
    return socketio.test_client(app, flask_test_client=flask_client)


def got(client):
    return [(m["name"], m["args"][0] if m["args"] else None) for m in client.get_received()]


def names(items):
    return [n for n, _ in items]


def join(app, user_id):
    c = connect(app, user_id)
    c.emit("join", {"request_id": 7})
    return c


def test_anonymous_sockets_are_refused(app, live):
    c = socketio.test_client(app, flask_test_client=app.test_client())
    assert not c.is_connected()


def test_a_deactivated_account_is_refused(app, live, monkeypatch):
    monkeypatch.setattr(user_service, "get_user_by_id", lambda uid: dict(USERS[1], is_active=0))
    assert not connect(app, 1).is_connected()


def test_joining_returns_the_room_details_and_history(app, live):
    s = join(app, 1)
    items = dict(got(s))
    info = items["joined"]
    assert info["role"] == "student" and info["peer_present"] is False
    assert info["ice_servers"] == ll.build_ice_servers(app.config)
    assert info["messages"][0]["text"] == "<b>Welcome</b>" and "2:00 PM" in info["messages"][0]["at"]


def test_the_second_person_triggers_the_offer_from_the_first(app, live):
    s = join(app, 1)
    s.get_received()
    t = join(app, 2)
    joined = dict(got(t))["joined"]
    assert joined["role"] == "tutor" and joined["peer_present"] is True
    seen = got(s)
    assert names(seen) == ["peer_joined"] and seen[0][1]["role"] == "tutor"


def test_only_people_in_the_booking_can_join(app, live):
    for user_id in (3, 4):
        c = join(app, user_id)
        assert got(c)[0][0] == "error_msg"
    assert sockets._rooms == {}
    c = connect(app, 1)
    c.emit("join", {"request_id": 999})
    c.emit("join", {"request_id": True})
    c.emit("join", "garbage")
    assert names(got(c)) == ["error_msg"] * 3 and sockets._rooms == {}


@pytest.mark.parametrize("changes,fragment", [
    ({"start_at": T(hours=3), "end_at": T(hours=4)}, "opens"),
    ({"status": "cancelled"}, "not confirmed")])
def test_a_room_that_is_not_open_cannot_be_joined(app, live, changes, fragment):
    live["req"] = booking(**changes)
    items = got(join(app, 1))
    assert items[0][0] == "error_msg" and fragment in items[0][1]["error"] and sockets._rooms == {}


def test_signals_are_cleaned_and_relayed_to_the_other_person_only(app, live):
    s, t = join(app, 1), join(app, 2)
    s.get_received(); t.get_received()
    s.emit("signal", {"type": "offer", "data": {"type": "offer", "sdp": SDP, "evil": "drop me"}})
    seen = got(t)
    assert names(seen) == ["signal"] and seen[0][1] == {"type": "offer", "data": {"type": "offer", "sdp": SDP}}
    assert got(s) == []                                                       # not echoed to the sender
    s.emit("signal", {"type": "hack", "data": {}})
    assert got(t) == []                                                       # invalid: not relayed


def test_signals_before_joining_go_nowhere(app, live):
    t = join(app, 2)
    t.get_received()
    outsider = connect(app, 1)
    outsider.emit("signal", {"type": "offer", "data": {"type": "offer", "sdp": SDP}})
    assert got(t) == [] and got(outsider) == []


def test_chat_is_saved_and_sent_to_both_people(app, live):
    s, t = join(app, 1), join(app, 2)
    s.get_received(); t.get_received()
    s.emit("chat", {"text": "  Hello <b>there</b>  "})
    for client in (s, t):
        seen = got(client)
        assert names(seen) == ["chat"] and seen[0][1]["text"] == "Hello <b>there</b>"
        assert seen[0][1]["role"] == "student" and seen[0][1]["name"] == "Sample Student"
    assert live["saved"] == [(7, 1, "Hello <b>there</b>")]                    # the user id came from the login


def test_bad_chat_is_refused(app, live):
    s = join(app, 1)
    s.get_received()
    for bad in ({"text": ""}, {"text": "x" * 1001}, {"text": 5}, {}, "garbage"):
        s.emit("chat", bad)
    assert names(got(s)) == ["error_msg"] * 5 and live["saved"] == []


def test_chat_before_joining_is_ignored(app, live):
    c = connect(app, 1)
    c.emit("chat", {"text": "hi"})
    assert got(c) == [] and live["saved"] == []


def test_chat_is_rate_limited(app, live):
    s = join(app, 1)
    s.get_received()
    for i in range(8):
        s.emit("chat", {"text": f"m{i}"})
    errors = [p["error"] for n, p in got(s) if n == "error_msg"]
    assert len(live["saved"]) == 6 and len(errors) == 2 and "too quickly" in errors[0]


def test_chat_failures_are_reported_and_a_full_chat_is_refused(app, live, monkeypatch):
    s = join(app, 1)
    s.get_received()
    live["count"] = chat.MAX_MESSAGES
    s.emit("chat", {"text": "hi"})
    assert "chat is full" in got(s)[0][1]["error"] and live["saved"] == []
    live["count"] = 0

    def broken(rid, uid, text):
        raise RuntimeError("db down")
    monkeypatch.setattr(chat, "add_message", broken)
    s.emit("chat", {"text": "hi"})
    assert "could not be sent" in got(s)[0][1]["error"]


def test_a_room_stops_working_after_its_deadline(app, live):
    s = join(app, 1)
    s.get_received()
    sid = next(iter(sockets._rooms))
    sockets._rooms[sid]["deadline"] = utcnow() - timedelta(minutes=1)
    s.emit("chat", {"text": "late"})
    assert "has closed" in got(s)[0][1]["error"] and live["saved"] == []


def test_leaving_tells_the_other_person(app, live):
    s, t = join(app, 1), join(app, 2)
    s.get_received(); t.get_received()
    t.disconnect()
    seen = got(s)
    assert names(seen) == ["peer_left"] and len(sockets._rooms) == 1


def test_a_second_tab_replaces_the_first(app, live):
    first = join(app, 1)
    first.get_received()
    second = join(app, 1)
    assert not first.is_connected()
    assert len(sockets._rooms) == 1 and "joined" in names(got(second))


# ======================= headers, files and code hygiene =======================
def test_the_camera_and_microphone_are_allowed_for_our_own_pages(client):
    policy = client.get("/login").headers["Permissions-Policy"]
    assert "camera=(self)" in policy and "microphone=(self)" in policy and "geolocation=()" in policy


def test_the_about_page_describes_live_sessions(client):
    page = client.get("/about")
    assert b"Video and audio go directly" in page.data and b"Live session chat" in page.data


def test_the_socketio_client_file_is_present():
    path = ROOT / "app" / "static" / "js" / "socket.io.min.js"
    assert path.exists() and path.stat().st_size > 10_000, \
        "Download socket.io.min.js into app/static/js (see the Phase 16 instructions)."


def test_the_session_script_never_uses_innerhtml():
    script = (ROOT / "app" / "static" / "js" / "session.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert banned not in script


def test_the_server_does_not_touch_media():
    source = (ROOT / "app" / "sockets.py").read_text(encoding="utf-8")
    for word in ("record", "ffmpeg", "write_bytes", "open("):
        assert word not in source