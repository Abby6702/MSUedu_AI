"""Run with:  python -m pytest -v
MySQL is faked. Socket.IO tests use its built-in test client (no browser). Real ZIPs and images are
built in memory so the file checks run on genuine data."""
import io
import zipfile
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app import create_app, sockets
from app.extensions import socketio
from app.services import file_service as fs, request_service, user_service
from app.services import session_chat_service as chat
from app.services import whiteboard_logic as wb
from app.timeutil import utcnow
from app.upload_limits import UPLOAD_PATH
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P17Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def app(tmp_path):
    app = create_app(P17Config)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)           # uploads go to a throw-away folder
    return app


@pytest.fixture
def client(app):
    return app.test_client()


USERS = {1: {"id": 1, "full_name": "Sample Student", "email": "s@example.com", "role": "student", "is_active": 1},
         2: {"id": 2, "full_name": "Sample Tutor", "email": "t@example.com", "role": "tutor", "is_active": 1},
         3: {"id": 3, "full_name": "Other Student", "email": "o@example.com", "role": "student", "is_active": 1},
         4: {"id": 4, "full_name": "An Admin", "email": "a@example.com", "role": "admin", "is_active": 1}}


def T(**kw):
    return utcnow() + timedelta(**kw)


def booking(**changes):
    base = {"id": 7, "student_id": 1, "tutor_id": 2, "status": "accepted", "topic": "Loops",
            "subject_name": "Python Programming", "student_name": "Sample Student",
            "tutor_name": "Sample Tutor", "start_at": T(minutes=-5), "end_at": T(minutes=55)}
    base.update(changes)
    return base


def login_as(client, monkeypatch, user_id=1):
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: USERS[user_id])
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


# ======================= whiteboard: cleaning messages =======================
def stroke(op_id="s1", points=None, **changes):
    base = {"id": op_id, "kind": "stroke", "tool": "pen", "color": "#FF0000", "size": 5,
            "points": points if points is not None else [[0.1, 0.2], [0.3, 0.4]]}
    base.update(changes)
    return base


def text_op(op_id="s2", **changes):
    base = {"id": op_id, "kind": "text", "x": 0.5, "y": 0.5, "text": "  Hi \n there ",
            "color": "#000000", "size": 24}
    base.update(changes)
    return base


def test_a_good_stroke_is_rebuilt_with_known_fields_only():
    op = wb.clean_draw(stroke(points=[[0.123456, 1], [0, 0.5]], evil="x"))
    assert op == {"id": "s1", "kind": "stroke", "tool": "pen", "color": "#ff0000", "size": 5,
                  "points": [[0.1235, 1.0], [0.0, 0.5]]}


def test_the_eraser_always_paints_white():
    assert wb.clean_draw(stroke(tool="eraser", color="not-a-color"))["color"] == "#ffffff"


@pytest.mark.parametrize("bad", [
    None, "x", [], {}, stroke(op_id="x1"), stroke(op_id="s"), stroke(op_id="s" + "a" * 32),
    stroke(op_id="s bad"), stroke(op_id="../x"), stroke(kind="line"), stroke(tool="brush"),
    stroke(color="red"), stroke(color="#12"), stroke(color="#GGGGGG"), stroke(color=None),
    stroke(size=0), stroke(size=41), stroke(size=True), stroke(size=5.5), stroke(size="5"),
    stroke(points=[]), stroke(points="x"), stroke(points=[[0.1, 0.1]] * 101), stroke(points=[[2, 0]]),
    stroke(points=[[0]]), stroke(points=[[True, 0]]), stroke(points=[[float("nan"), 0]]),
    stroke(points=[[0, 0, 0]]), stroke(points=[["a", "b"]])])
def test_bad_strokes_are_rejected(bad):
    assert wb.clean_draw(bad) is None


def test_text_is_cleaned_and_bad_text_rejected():
    assert wb.clean_draw(text_op())["text"] == "Hi there"
    for bad in (text_op(text=""), text_op(text="\u202e"), text_op(text="x" * 201), text_op(text=5),
                text_op(size=11), text_op(size=65), text_op(x=1.5), text_op(color="blue")):
        assert wb.clean_draw(bad) is None


# ======================= whiteboard: the board =======================
def clean(op):
    return wb.clean_draw(op)


def test_a_stroke_grows_in_chunks_and_each_chunk_is_relayed():
    board = wb.Board()
    first = board.draw("student", clean(stroke("s1", [[0, 0], [0.1, 0.1]])))
    second = board.draw("student", clean(stroke("s1", [[0.2, 0.2]])))
    assert first["points"] == [[0, 0], [0.1, 0.1]] and second["points"] == [[0.2, 0.2]]
    snapshot = board.snapshot()
    assert len(snapshot) == 1 and snapshot[0]["points"] == [[0, 0], [0.1, 0.1], [0.2, 0.2]]


def test_nobody_can_draw_or_extend_as_the_other_person():
    board = wb.Board()
    assert board.draw("tutor", clean(stroke("s1"))) is None                     # wrong id letter
    board.draw("student", clean(stroke("s1")))
    assert board.draw("tutor", clean(stroke("s1"))) is None
    assert board.draw("student", clean(text_op("s1"))) is None                  # id already used
    board.draw("student", clean(text_op("s2")))
    assert board.draw("student", clean(text_op("s2"))) is None                  # no duplicate text


def test_the_size_caps(monkeypatch):
    monkeypatch.setattr(wb, "MAX_OPS", 2)
    board = wb.Board()
    assert board.draw("student", clean(text_op("s1"))) and board.draw("student", clean(text_op("s2")))
    assert board.draw("student", clean(text_op("s3"))) is None

    monkeypatch.setattr(wb, "MAX_OPS", 100)
    monkeypatch.setattr(wb, "MAX_STROKE_POINTS", 3)
    board = wb.Board()
    assert len(board.draw("student", clean(stroke("s1", [[0, 0]] * 5)))["points"]) == 3
    assert board.draw("student", clean(stroke("s1", [[0.5, 0.5]]))) is None     # the stroke is full

    monkeypatch.setattr(wb, "MAX_STROKE_POINTS", 3000)
    monkeypatch.setattr(wb, "MAX_TOTAL_POINTS", 4)
    board = wb.Board()
    assert board.draw("student", clean(stroke("s1", [[0, 0]] * 3)))
    assert board.draw("student", clean(stroke("s2", [[0, 0]] * 3))) is None     # the board is full


def test_undo_and_redo_only_touch_your_own_work():
    board = wb.Board()
    for who, op_id in (("student", "s1"), ("tutor", "t1"), ("student", "s2")):
        board.draw(who, clean(stroke(op_id)))
    assert board.undo("student") == "s2" and [o["id"] for o in board.snapshot()] == ["s1", "t1"]
    assert board.undo("tutor") == "t1" and board.undo("tutor") is None
    assert board.redo("student")["id"] == "s2" and [o["id"] for o in board.snapshot()] == ["s1", "s2"]
    assert board.redo("student") is None and board.redo("tutor")["id"] == "t1"


def test_new_drawing_ends_the_redo_history_and_points_are_counted():
    board = wb.Board()
    board.draw("student", clean(stroke("s1")))
    board.draw("student", clean(stroke("s2")))
    assert board.points == 4
    board.undo("student")
    assert board.points == 2
    board.draw("student", clean(stroke("s3")))
    assert board.redo("student") is None
    board.undo("student"); board.undo("student")
    assert board.points == 0


def test_clear_and_snapshot_copies():
    board = wb.Board()
    board.draw("student", clean(stroke("s1")))
    snapshot = board.snapshot()
    snapshot[0]["points"].append([0.9, 0.9])
    assert len(board.snapshot()[0]["points"]) == 2                              # a copy, not the original
    board.undo("student")
    assert board.clear("tutor") is True and board.snapshot() == []
    assert board.redo("student") is None                                        # clear also ends redo


# ======================= whiteboard: real-time events =======================
@pytest.fixture
def live(monkeypatch):
    sockets._rooms.clear()
    sockets._boards.clear()
    monkeypatch.setattr(user_service, "get_user_by_id", lambda uid: USERS.get(uid))
    monkeypatch.setattr(request_service, "get_for_user", lambda rid, uid: booking(id=rid)
                        if rid in (7, 8) and uid in (1, 2) else None)
    monkeypatch.setattr(chat, "recent", lambda rid, limit: [])
    monkeypatch.setattr(chat, "count", lambda rid: 0)
    monkeypatch.setattr(chat, "add_message", lambda *a: None)
    yield
    sockets._rooms.clear()
    sockets._boards.clear()


def connect(app, user_id):
    flask_client = app.test_client()
    with flask_client.session_transaction() as sess:
        sess["user_id"] = user_id
    return socketio.test_client(app, flask_test_client=flask_client)


def got(c):
    return [(m["name"], m["args"][0] if m["args"] else None) for m in c.get_received()]


def names(items):
    return [n for n, _ in items]


def join(app, user_id, request_id=7):
    c = connect(app, user_id)
    c.emit("join", {"request_id": request_id})
    return c


def pair(app):
    s, t = join(app, 1), join(app, 2)
    s.get_received(); t.get_received()
    return s, t


def test_joining_sends_the_board_so_far(app, live):
    s = join(app, 1)
    assert dict(got(s))["wb_state"] == {"ops": []}
    s.emit("wb_draw", stroke("s1"))
    t = join(app, 2)
    state = dict(got(t))["wb_state"]
    assert [o["id"] for o in state["ops"]] == ["s1"] and state["ops"][0]["color"] == "#ff0000"


def test_drawing_reaches_the_other_person_only(app, live):
    s, t = pair(app)
    s.emit("wb_draw", stroke("s1"))
    seen = got(t)
    assert names(seen) == ["wb_draw"] and seen[0][1]["id"] == "s1" and seen[0][1]["points"] == [[0.1, 0.2], [0.3, 0.4]]
    assert got(s) == []
    s.emit("wb_draw", stroke("s1", [[0.5, 0.5]]))
    assert got(t)[0][1]["points"] == [[0.5, 0.5]]                               # just the new chunk


def test_bad_or_forged_drawing_is_never_relayed(app, live):
    s, t = pair(app)
    s.emit("wb_draw", stroke("t1"))                                             # a student using a tutor id
    s.emit("wb_draw", stroke("s9", size=999))
    s.emit("wb_draw", "garbage")
    assert got(t) == []
    sockets._boards[7]["board"].snapshot() == []


def test_drawing_before_joining_goes_nowhere(app, live):
    s, t = pair(app)
    outsider = connect(app, 1)
    outsider.emit("wb_draw", stroke("s1"))
    outsider.emit("wb_undo")
    assert got(t) == [] and got(outsider) == []


def test_undo_removes_the_item_for_both_people(app, live):
    s, t = pair(app)
    s.emit("wb_draw", stroke("s1")); t.get_received()
    s.emit("wb_undo")
    assert got(s) == [("wb_remove", {"id": "s1"})] and got(t) == [("wb_remove", {"id": "s1"})]
    s.emit("wb_undo")
    assert got(s) == []                                                         # nothing left to undo


def test_one_person_cannot_undo_the_others_work(app, live):
    s, t = pair(app)
    s.emit("wb_draw", stroke("s1")); t.get_received()
    t.emit("wb_undo")
    assert got(s) == [] and got(t) == []


def test_redo_brings_the_item_back_for_both(app, live):
    s, t = pair(app)
    s.emit("wb_draw", stroke("s1")); t.get_received()
    s.emit("wb_undo"); s.get_received(); t.get_received()
    s.emit("wb_redo")
    for c in (s, t):
        seen = got(c)
        assert names(seen) == ["wb_add"] and seen[0][1]["id"] == "s1" and len(seen[0][1]["points"]) == 2


def test_clear_empties_the_board_for_everyone(app, live):
    s, t = pair(app)
    s.emit("wb_draw", stroke("s1"))
    t.emit("wb_clear")
    assert names(got(s)).count("wb_clear") == 1 and names(got(t)).count("wb_clear") == 1
    late = join(app, 1, 7)                                                      # a second tab later
    assert dict(got(late))["wb_state"] == {"ops": []}


def test_the_board_survives_everyone_leaving_while_the_room_is_open(app, live):
    s = join(app, 1)
    s.emit("wb_draw", stroke("s1"))
    s.disconnect()
    assert sockets._rooms == {}
    again = join(app, 1)
    assert [o["id"] for o in dict(got(again))["wb_state"]["ops"]] == ["s1"]


def test_boards_of_closed_empty_rooms_are_forgotten(app, live):
    s = join(app, 1, 7)
    s.emit("wb_draw", stroke("s1"))
    s.disconnect()
    sockets._boards[7]["deadline"] = utcnow() - timedelta(minutes=1)
    join(app, 1, 8)                                                             # someone joins another room
    assert 7 not in sockets._boards and 8 in sockets._boards


def test_board_commands_are_rate_limited(app, live):
    s = join(app, 1)
    s.get_received()
    for _ in range(62):
        s.emit("wb_clear")
    assert names(got(s)).count("wb_clear") == 60


def test_a_closed_room_stops_the_board(app, live):
    s, t = pair(app)
    for info in sockets._rooms.values():
        info["deadline"] = utcnow() - timedelta(minutes=1)
    s.emit("wb_draw", stroke("s1"))
    assert "has closed" in got(s)[0][1]["error"] and got(t) == []


# ======================= files: names and contents =======================
def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in entries:
            archive.writestr(name, "<x/>")
    return buf.getvalue()


def image(fmt, size=(80, 60)):
    buf = io.BytesIO()
    Image.new("RGB" if fmt == "JPEG" else "P", size, "red").save(buf, fmt)
    return buf.getvalue()


PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
DOCX = make_zip(["[Content_Types].xml", "word/document.xml"])
PPTX = make_zip(["[Content_Types].xml", "ppt/presentation.xml"])
PNG, JPEG, GIF = image("PNG"), image("JPEG"), image("GIF")


def test_names_are_cleaned():
    assert fs.sanitize_name("a/b\\c.pdf") == "c.pdf"
    assert fs.sanitize_name("re\u202eport.pdf") == "report.pdf"
    assert fs.sanitize_name('we<ir>d:na"me?.pdf') == "we_ir_d_na_me_.pdf"
    assert fs.sanitize_name("  notes   final .txt ") == "notes final .txt"
    assert fs.sanitize_name("name. ") == "name" and fs.sanitize_name("..") == "" and fs.sanitize_name(None) == ""
    assert fs.sanitize_name("R\u00e9sum\u00e9 \u00f1.docx") == "R\u00e9sum\u00e9 \u00f1.docx"
    long_name = fs.sanitize_name("x" * 200 + ".pdf")
    assert len(long_name) == fs.MAX_NAME and long_name.endswith(".pdf")


def test_human_size():
    assert fs.human_size(500) == "500 B" and fs.human_size(2048) == "2 KB" and fs.human_size(1_572_864) == "1.5 MB"


def test_the_real_type_is_found_from_the_contents():
    assert [fs.detect_kind(d) for d in (PDF, DOCX, PPTX, PNG, JPEG, GIF, b"hello\nworld\n")] == [
        "pdf", "docx", "pptx", "png", "jpeg", "gif", "txt"]
    assert fs.detect_kind(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert fs.detect_kind(b"<html><script>alert(1)</script></html>") == "txt"   # text, served as a download
    for bad in (b"MZ\x90\x00binary", b"a\x00b", b"\x01\x02 control", b"PK\x03\x04garbage", b""):
        assert fs.detect_kind(bad) is None


def test_macro_documents_and_empty_zips_are_refused():
    macro = make_zip(["[Content_Types].xml", "word/document.xml", "word/vbaProject.bin"])
    assert fs.detect_kind(macro) is None
    assert fs.detect_kind(make_zip(["readme.txt"])) is None
    assert fs.detect_kind(make_zip(["[Content_Types].xml"])) is None


def test_zip_size_limits(monkeypatch):
    monkeypatch.setattr(fs, "MAX_ENTRIES", 1)
    assert fs.detect_kind(DOCX) is None
    monkeypatch.setattr(fs, "MAX_ENTRIES", 2000)
    monkeypatch.setattr(fs, "MAX_UNPACKED", 3)
    assert fs.detect_kind(DOCX) is None


@pytest.mark.parametrize("name,data,fragment", [
    ("notes.pdf", b"", "empty"),
    ("virus.exe", PDF, "not allowed"), ("page.html", b"hello", "not allowed"),
    ("report.pdf.exe", PDF, "not allowed"), ("noextension", PDF, "not allowed"),
    ("photo.png", PDF, "do not match"), ("notes.pdf", PNG, "do not match"),
    ("fake.docx", b"not a zip at all", "do not match"), ("fake.pptx", DOCX, "do not match"),
    ("fake.png", b"\x89PNG\r\n\x1a\n" + b"junk", "could not be read"),
        ("big.pdf", PDF + b"x" * fs.MAX_FILE_BYTES, "too large"), ("", PDF, "Choose a file")],
        ids=["empty-file", "exe", "html", "compound-extension", "no-extension", "wrong-png-content",
            "wrong-pdf-content", "invalid-docx", "invalid-pptx", "unreadable-png", "oversized", "empty-name"])
def test_bad_uploads_are_refused_with_a_clear_message(name, data, fragment):
    with pytest.raises(fs.FileError, match=fragment):
        fs.validate_upload(name, data)


def test_good_uploads_are_accepted():
    assert fs.validate_upload("Notes.PDF", PDF) == ("pdf", "Notes.PDF")
    assert fs.validate_upload("a.jpeg", JPEG)[0] == "jpeg" and fs.validate_upload("a.jpg", JPEG)[0] == "jpeg"
    assert fs.validate_upload("t.txt", b"hello\n") == ("txt", "t.txt")
    assert fs.validate_upload("w.docx", DOCX)[0] == "docx" and fs.validate_upload("p.pptx", PPTX)[0] == "pptx"
    assert fs.validate_upload("i.png", PNG)[0] == "png" and fs.validate_upload("i.gif", GIF)[0] == "gif"


def test_images_with_too_many_pixels_are_refused(monkeypatch):
    monkeypatch.setattr(fs, "MAX_PIXELS", 100)
    with pytest.raises(fs.FileError, match="too many pixels"):
        fs.validate_upload("big.png", PNG)


# ======================= files: storing =======================
def test_saving_stores_under_a_random_name_and_registers_it(app, monkeypatch):
    added = {}
    monkeypatch.setattr(fs, "totals", lambda rid: {"n": 0, "total": 0})
    monkeypatch.setattr(fs, "add_file", lambda *a: added.update(args=a) or 12)
    with app.app_context():
        row = fs.save_upload(7, 1, "Sample Student", "student", "My Notes.pdf", PDF)
        stored = added["args"][3]
        assert fs.NAME_RE.match(stored) and "Notes" not in stored
        assert (fs.files_dir() / stored).read_bytes() == PDF
    assert row["id"] == 12 and row["original_name"] == "My Notes.pdf" and row["size_label"] == f"{len(PDF)} B"


def test_a_failed_database_insert_leaves_no_orphan_file(app, monkeypatch):
    monkeypatch.setattr(fs, "totals", lambda rid: {"n": 0, "total": 0})

    def broken(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(fs, "add_file", broken)
    with app.app_context():
        with pytest.raises(RuntimeError):
            fs.save_upload(7, 1, "S", "student", "a.pdf", PDF)
        assert list(fs.files_dir().iterdir()) == []


def test_session_limits(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(fs, "totals", lambda rid: {"n": fs.MAX_FILES, "total": 0})
        with pytest.raises(fs.FileError, match="already has"):
            fs.save_upload(7, 1, "S", "student", "a.pdf", PDF)
        monkeypatch.setattr(fs, "totals", lambda rid: {"n": 1, "total": fs.MAX_TOTAL_BYTES})
        with pytest.raises(fs.FileError, match="25 MB"):
            fs.save_upload(7, 1, "S", "student", "a.pdf", PDF)
        assert list(fs.files_dir().iterdir()) == []                               # nothing stored when refused


def test_delete_stored_ignores_unsafe_names(app, tmp_path):
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"keep me")
    with app.app_context():
        for bad in ("../secret.pdf", "..\\secret.pdf", "x.pdf", None, ""):
            fs.delete_stored(bad)
    assert secret.exists()


# ======================= files: routes =======================
ROW = {"id": 5, "original_name": "<b>notes</b>.pdf", "kind": "pdf", "size_bytes": 10, "size_label": "10 B",
       "created_at": datetime(2026, 10, 5, 6, 0), "uploader": "Sample Student", "role": "student"}
BASE = "/sessions/7/files"


@pytest.fixture
def env(monkeypatch):
    e = {"booking": booking(), "saved": [], "deleted": [], "stored_deleted": [], "emitted": [],
         "file": None, "save_error": None}
    monkeypatch.setattr(request_service, "get_for_user",
                        lambda rid, uid: e["booking"] if uid in (1, 2) and rid == 7 else None)
    monkeypatch.setattr(fs, "list_files", lambda rid: [dict(ROW)])
    monkeypatch.setattr(fs, "get_file", lambda rid, fid: e["file"])

    def fake_save(rid, uid, name, role, filename, data):
        if e["save_error"]:
            raise e["save_error"]
        e["saved"].append((rid, uid, name, role, filename, data))
        return dict(ROW, original_name=filename)
    monkeypatch.setattr(fs, "save_upload", fake_save)
    monkeypatch.setattr(fs, "delete_row", lambda fid, rid, uid: e["deleted"].append((fid, rid, uid)))
    monkeypatch.setattr(fs, "delete_stored", lambda name: e["stored_deleted"].append(name))
    monkeypatch.setattr(socketio, "emit", lambda event, payload=None, **kw: e["emitted"].append((event, payload, kw)))
    return e


def post_file(client, content=PDF, name="notes.pdf"):
    return client.post(BASE, data={"file": (io.BytesIO(content), name)}, content_type="multipart/form-data")


ALL = [("get", BASE), ("post", BASE), ("get", BASE + "/5"), ("post", BASE + "/5/delete")]


def test_only_the_two_people_of_a_session_can_use_files(client, monkeypatch, env):
    for method, url in ALL:
        assert getattr(client, method)(url).status_code == 302                    # not logged in
    login_as(client, monkeypatch, 4)
    for method, url in ALL:
        assert getattr(client, method)(url).status_code == 403                    # an administrator
    login_as(client, monkeypatch, 3)
    for method, url in ALL:
        assert getattr(client, method)(url).status_code == 404                    # someone else's booking
    assert env["saved"] == [] and env["deleted"] == []


@pytest.mark.parametrize("status", ["pending", "cancelled", "declined"])
def test_files_need_a_confirmed_or_completed_booking(client, monkeypatch, env, status):
    login_as(client, monkeypatch, 1)
    env["booking"] = booking(status=status)
    assert client.get(BASE).status_code == 404 and post_file(client).status_code == 404


def test_listing_files(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    item = client.get(BASE).get_json()["files"][0]
    assert item["name"] == "<b>notes</b>.pdf" and item["role"] == "student"
    assert item["url"] == "/sessions/7/files/5" and "2:00 PM" in item["at"]


def test_a_good_upload_is_saved_for_the_logged_in_person_and_announced(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    response = post_file(client)
    assert response.status_code == 200 and response.get_json()["file"]["name"] == "notes.pdf"
    assert env["saved"] == [(7, 1, "Sample Student", "student", "notes.pdf", PDF)]
    event, payload, kwargs = env["emitted"][0]
    assert event == "file_added" and kwargs["to"] == "session:7" and payload["file"]["id"] == 5


def test_uploads_are_refused_when_the_room_is_not_open(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    for changes in ({"start_at": T(hours=3), "end_at": T(hours=4)},
                    {"start_at": T(hours=-5), "end_at": T(hours=-4)}, {"status": "completed"}):
        env["booking"] = booking(**changes)
        assert post_file(client).status_code == 403
    assert env["saved"] == []
    assert client.get(BASE).status_code == 200 if env["booking"]["status"] == "completed" else True


def test_upload_problems_give_clear_json_errors(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    assert client.post(BASE, data={}, content_type="multipart/form-data").status_code == 400
    env["save_error"] = fs.FileError("This file type is not allowed.")
    response = post_file(client, name="virus.exe")
    assert response.status_code == 400 and response.get_json()["error"] == "This file type is not allowed."
    env["save_error"] = RuntimeError("disk full")
    response = post_file(client)
    assert response.status_code == 500 and "disk full" not in response.get_data(as_text=True)
    assert env["emitted"] == []


def test_a_failed_announcement_does_not_break_the_upload(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)

    def broken(*a, **k):
        raise RuntimeError("socket down")
    monkeypatch.setattr(socketio, "emit", broken)
    assert post_file(client).status_code == 200


def test_the_upload_route_alone_accepts_bigger_requests(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    assert post_file(client, b"%PDF-" + b"x" * (2 * 1024 * 1024)).status_code == 200    # over 1 MB, under 5 MB
    assert post_file(client, b"%PDF-" + b"x" * (6 * 1024 * 1024)).status_code == 413    # over the upload limit
    other = client.post("/login", data={"email": "x" * (2 * 1024 * 1024)})
    assert other.status_code == 413                                                     # the rest of the site stays at 1 MB


def test_the_upload_path_pattern():
    assert UPLOAD_PATH.match("/sessions/12/files")
    for path in ("/sessions/12/files/3", "/sessions/12", "/sessions/x/files", "/student/sessions/12/files"):
        assert not UPLOAD_PATH.match(path)


def stored_file(app, kind="pdf", ext=".pdf", data=PDF):
    with app.app_context():
        name = "a" * 32 + ext
        (fs.files_dir() / name).write_bytes(data)
    return {"id": 5, "user_id": 1, "original_name": "notes.pdf", "stored_name": name, "kind": kind, "size_bytes": len(data)}


def test_downloads_are_always_attachments_with_the_right_type(app, client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["file"] = stored_file(app)
    response = client.get(BASE + "/5")
    assert response.status_code == 200 and response.data == PDF and response.mimetype == "application/pdf"
    assert "attachment" in response.headers["Content-Disposition"] and "notes.pdf" in response.headers["Content-Disposition"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    env["file"] = dict(stored_file(app, "txt", ".txt", b"<script>alert(1)</script>"), original_name="a.txt")
    page = client.get(BASE + "/5")
    assert page.mimetype == "text/plain" and "attachment" in page.headers["Content-Disposition"]


def test_downloads_are_still_possible_after_the_session(app, client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    env["booking"] = booking(status="completed", start_at=T(hours=-5), end_at=T(hours=-4))
    env["file"] = stored_file(app)
    assert client.get(BASE + "/5").status_code == 200


def test_tampered_missing_or_foreign_files_are_never_served(app, client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    assert client.get(BASE + "/5").status_code == 404                                  # no such file in this session
    for bad in ("../../secret.pdf", "x.pdf", "a" * 32 + ".exe"):
        env["file"] = dict(stored_file(app), stored_name=bad)
        assert client.get(BASE + "/5").status_code == 404
    env["file"] = dict(stored_file(app), stored_name="b" * 32 + ".pdf")                # row exists, file does not
    assert client.get(BASE + "/5").status_code == 404


def test_you_can_remove_only_your_own_files(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    env["file"] = {"id": 5, "user_id": 2, "stored_name": "a" * 32 + ".pdf"}
    assert client.post(BASE + "/5/delete").status_code == 403 and env["deleted"] == []
    env["file"] = {"id": 5, "user_id": 1, "stored_name": "a" * 32 + ".pdf"}
    assert client.post(BASE + "/5/delete").status_code == 200
    assert env["deleted"] == [(5, 7, 1)] and env["stored_deleted"] == ["a" * 32 + ".pdf"]
    assert env["emitted"][0][0] == "file_removed" and env["emitted"][0][1] == {"id": 5}
    env["file"] = None
    assert client.post(BASE + "/9/delete").status_code == 404


# ======================= the page =======================
def test_the_room_has_a_whiteboard_and_a_files_panel(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    page = client.get("/sessions/7")
    for expected in (b'id="wbCanvas"', b'id="fileInput"', b'data-files-url="/sessions/7/files"',
                     b"js/whiteboard.js", b"js/session_files.js", b"js/workspace.js", b"not recorded"):
        assert expected in page.data
    assert b"Phase 17" not in page.data


def test_a_closed_room_lists_files_for_download_and_escapes_names(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    env["booking"] = booking(start_at=T(hours=3), end_at=T(hours=4))
    page = client.get("/sessions/7")
    assert page.status_code == 200 and b"/sessions/7/files/5" in page.data
    assert b"<b>notes</b>" not in page.data and b"&lt;b&gt;notes" in page.data and b"session.js" not in page.data


def test_a_pending_booking_never_lists_files(client, monkeypatch, env):
    login_as(client, monkeypatch, 1)
    env["booking"] = booking(status="pending")

    def fail(rid):
        raise AssertionError("must not list files for an unconfirmed booking")
    monkeypatch.setattr(fs, "list_files", fail)
    assert client.get("/sessions/7").status_code == 200


# ======================= code hygiene =======================
@pytest.mark.parametrize("script", ["whiteboard.js", "session_files.js", "workspace.js"])
def test_the_room_scripts_never_use_innerhtml(script):
    source = (ROOT / "app" / "static" / "js" / script).read_text(encoding="utf-8")
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert banned not in source


def test_the_whiteboard_rules_are_pure():
    source = (ROOT / "app" / "services" / "whiteboard_logic.py").read_text(encoding="utf-8")
    for word in ("flask", "app.db", "requests", "socket"):
        assert word not in source


def test_the_about_page_mentions_shared_files_and_the_board(client):
    page = client.get("/about")
    assert b"Shared files are stored" in page.data and b"Whiteboard drawings" in page.data