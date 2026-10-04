"""Run with:  python -m pytest -v   (MySQL is faked; real images are made with Pillow.)"""
import io
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from app import create_app
from app import validators_people as vpp
from app.services import people_service as ps, photo_service as ph
from app.services import progress_service as prog, tutor_service, user_service
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P15Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def app(tmp_path):
    app = create_app(P15Config)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)           # photos go to a throw-away folder
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


def image_bytes(fmt="PNG", size=(300, 200), mode="RGB", color="red"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt)
    return buf.getvalue()


JPEG_BYTES = image_bytes("JPEG")


# ======================= checking images =======================
def test_sniff_reads_the_real_type():
    assert ph.sniff(image_bytes("PNG")) == "png" and ph.sniff(JPEG_BYTES) == "jpeg"
    assert ph.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert ph.sniff(image_bytes("GIF", mode="P")) is None
    assert ph.sniff(b"<script>alert(1)</script>") is None and ph.sniff(b"") is None


def test_a_good_photo_becomes_a_clean_square_jpeg():
    out = Image.open(io.BytesIO(ph.process_image(image_bytes("PNG", (300, 200)))))
    assert out.format == "JPEG" and out.size == (400, 400) and len(out.getexif()) == 0


def test_transparent_areas_become_white():
    transparent = image_bytes("PNG", (200, 200), "RGBA", (255, 0, 0, 0))
    out = Image.open(io.BytesIO(ph.process_image(transparent))).convert("RGB")
    assert all(channel > 240 for channel in out.getpixel((200, 200)))


@pytest.mark.parametrize("data,fragment", [
    (b"", "Choose a photo"),
    (b"x" * (ph.MAX_BYTES + 1), "too large"),
    (b"this is not an image at all", "JPEG, PNG or WebP"),
    (b"<?php system($_GET['c']); ?>", "JPEG, PNG or WebP"),
    (image_bytes("GIF", mode="P"), "JPEG, PNG or WebP"),
    (image_bytes("PNG", (50, 50)), "too small"),
    (image_bytes("PNG", (4100, 4100), "L"), "too many pixels"),
    (image_bytes("PNG", (300, 300))[:60], "could not be read"),
], ids=["empty", "oversized", "plain-text", "php-payload", "gif", "too-small", "too-many-pixels", "truncated-png"])
def test_bad_uploads_are_refused_with_a_clear_message(data, fragment):
    with pytest.raises(ph.PhotoError, match=fragment):
        ph.process_image(data)


# ======================= storing files =======================
def test_saving_replaces_the_old_file_and_removing_deletes_it(app, monkeypatch):
    state = {"name": None}
    monkeypatch.setattr(ps, "get_details", lambda tid: {"photo_filename": state["name"]})
    monkeypatch.setattr(ps, "set_photo", lambda tid, name: state.update(name=name))
    with app.app_context():
        first = ph.save_photo(7, b"one")
        state["name"] = first
        second = ph.save_photo(7, b"two")
        state["name"] = second
        folder = ph.photo_dir()
        assert ph.NAME_RE.match(first) and ph.NAME_RE.match(second) and first != second
        assert not (folder / first).exists() and (folder / second).read_bytes() == b"two"
        ph.remove_photo(7)
        assert not (folder / second).exists()


def test_a_failed_database_update_leaves_no_orphan_file(app, monkeypatch):
    monkeypatch.setattr(ps, "get_details", lambda tid: {"photo_filename": None})

    def broken(tid, name):
        raise RuntimeError("db down")
    monkeypatch.setattr(ps, "set_photo", broken)
    with app.app_context():
        with pytest.raises(RuntimeError):
            ph.save_photo(7, b"data")
        assert list(ph.photo_dir().iterdir()) == []


def test_delete_ignores_unsafe_names(app, tmp_path):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"keep me")
    with app.app_context():
        ph.photo_dir()
        for bad in ("../secret.jpg", "..\\secret.jpg", "x.jpg", None, ""):
            ph.delete_file(bad)
    assert secret.exists()


# ======================= who may see a photo =======================
def test_who_may_see_a_photo():
    can = ps.can_view_photo
    assert can("admin", 1, 5, "pending", 1)
    assert can("tutor", 5, 5, "pending", 1) and not can("tutor", 6, 5, "approved", 1)
    assert can("student", 1, 5, "approved", 1)
    assert not can("student", 1, 5, "pending", 1) and not can("student", 1, 5, "rejected", 1)
    assert not can("student", 1, 5, "approved", 0) and not can("visitor", 1, 5, "approved", 1)


@pytest.fixture
def photo_file(app):
    with app.app_context():
        folder = ph.photo_dir()
    name = "a" * 32 + ".jpg"
    (folder / name).write_bytes(JPEG_BYTES)
    return name


def test_photos_are_served_only_to_people_allowed_to_see_them(client, monkeypatch, photo_file):
    info = {"photo_filename": photo_file, "approval_status": "approved", "is_active": 1}
    monkeypatch.setattr(ps, "photo_info", lambda tid: info)
    assert client.get("/media/tutors/5/photo").status_code == 302          # not logged in
    login_as(client, monkeypatch, "student")
    response = client.get("/media/tutors/5/photo")
    assert response.status_code == 200 and response.mimetype == "image/jpeg" and response.data == JPEG_BYTES
    info["approval_status"] = "pending"
    assert client.get("/media/tutors/5/photo").status_code == 404           # hidden until approved
    login_as(client, monkeypatch, "admin")
    assert client.get("/media/tutors/5/photo").status_code == 200
    login_as(client, monkeypatch, "tutor")                                  # this user is tutor 1
    assert client.get("/media/tutors/5/photo").status_code == 404           # not your photo
    assert client.get("/media/tutors/1/photo").status_code == 200           # your own


def test_tampered_or_missing_file_names_are_never_served(client, monkeypatch, tmp_path):
    login_as(client, monkeypatch, "admin")
    for name in ("../../secret.jpg", "..\\x.jpg", "short.jpg", None):
        monkeypatch.setattr(ps, "photo_info", lambda tid, n=name: {
            "photo_filename": n, "approval_status": "approved", "is_active": 1})
        assert client.get("/media/tutors/5/photo").status_code == 404
    monkeypatch.setattr(ps, "photo_info", lambda tid: None)
    assert client.get("/media/tutors/5/photo").status_code == 404
    monkeypatch.setattr(ps, "photo_info", lambda tid: {
        "photo_filename": "b" * 32 + ".jpg", "approval_status": "approved", "is_active": 1})
    assert client.get("/media/tutors/5/photo").status_code == 404           # file does not exist


# ======================= tutor pages =======================
@pytest.fixture
def tutor_env(monkeypatch):
    env = {"saved": [], "removed": [], "details": []}
    monkeypatch.setattr(ps, "get_details", lambda tid: {
        "skills": "Python, Calculus", "education": "BS Math", "experience": "Tutored",
        "photo_filename": None})
    monkeypatch.setattr(ph, "save_photo", lambda tid, data: env["saved"].append((tid, data)) or "f.jpg")
    monkeypatch.setattr(ph, "remove_photo", lambda tid: env["removed"].append(tid))
    monkeypatch.setattr(ps, "save_details", lambda tid, d: env["details"].append((tid, d)))
    return env


def upload(client, content, name="me.png"):
    return client.post("/tutor/profile-photo", data={"photo": (io.BytesIO(content), name)},
                       content_type="multipart/form-data", follow_redirects=True)


def test_only_tutors_can_edit_details_and_photos(client, monkeypatch, tutor_env):
    for role in ("student", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get("/tutor/profile-details").status_code == 403
        assert client.post("/tutor/profile-details", data={}).status_code == 403
        assert upload(client, JPEG_BYTES).status_code == 403
        assert client.post("/tutor/profile-photo/remove").status_code == 403
    assert tutor_env["saved"] == [] and tutor_env["details"] == []


def test_a_good_upload_is_cleaned_before_saving(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")
    page = upload(client, image_bytes("PNG", (300, 200)))
    assert b"Photo saved" in page.data
    tutor_id, data = tutor_env["saved"][0]
    assert tutor_id == 1 and Image.open(io.BytesIO(data)).size == (400, 400)   # the cleaned copy, not the original


def test_a_disguised_file_is_refused(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")
    page = upload(client, b"<script>alert(1)</script>", "evil.png")
    assert b"JPEG, PNG or WebP" in page.data and tutor_env["saved"] == []


def test_no_file_chosen(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")
    page = client.post("/tutor/profile-photo", data={}, follow_redirects=True)
    assert b"Choose a photo" in page.data and tutor_env["saved"] == []


def test_a_storage_failure_is_reported(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")

    def broken(tid, data):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ph, "save_photo", broken)
    assert b"Could not save the photo" in upload(client, JPEG_BYTES).data


def test_removing_a_photo(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")
    assert client.post("/tutor/profile-photo/remove").status_code == 302 and tutor_env["removed"] == [1]


def test_details_are_cleaned_and_saved(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")
    response = client.post("/tutor/profile-details", data={
        "skills": "Python, python, Calculus", "education": "BS Math", "experience": "Tutored for a year"})
    assert response.status_code == 302
    assert tutor_env["details"] == [(1, {"skills": "Python, Calculus", "education": "BS Math",
                                         "experience": "Tutored for a year"})]


@pytest.mark.parametrize("form,fragment", [
    ({"skills": ", ".join(f"s{i}" for i in range(11))}, b"at most 10"),
    ({"skills": "x" * 41}, b"40 characters"),
    ({"education": "x" * 301}, b"300 characters"),
    ({"experience": "x" * 1001}, b"1000 characters")])
def test_bad_details_are_not_saved(client, monkeypatch, tutor_env, form, fragment):
    login_as(client, monkeypatch, "tutor")
    page = client.post("/tutor/profile-details", data=form)
    assert page.status_code == 200 and fragment in page.data and tutor_env["details"] == []


def test_the_details_page_shows_current_values(client, monkeypatch, tutor_env):
    login_as(client, monkeypatch, "tutor")
    page = client.get("/tutor/profile-details")
    assert page.status_code == 200 and b"Python, Calculus" in page.data and b"location" in page.data


def test_skill_parsing():
    assert vpp.parse_skills(" Python, python ,Calculus,, \n Writing ") == ["Python", "Calculus", "Writing"]
    assert vpp.parse_skills("") == [] and vpp.parse_skills(None) == []


# ======================= My students =======================
ROW = {"id": 9, "full_name": "<b>Sample Student</b>", "course": "BSCS", "year_level": 2,
       "completed": 1, "upcoming": 1, "last_session": datetime(2026, 10, 5, 6, 0)}
SESSION = {"id": 3, "status": "completed", "start_at": datetime(2026, 10, 5, 6, 0),
           "end_at": datetime(2026, 10, 5, 7, 0), "topic": "Limits", "subject_name": "Calculus 1", "has_record": 1}


def test_my_students_is_for_tutors_only(client, monkeypatch):
    assert client.get("/tutor/students").status_code == 302
    for role in ("student", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get("/tutor/students").status_code == 403
        assert client.get("/tutor/students/9").status_code == 403


def test_my_students_list_escapes_names(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "list_students", lambda tid: [ROW])
    page = client.get("/tutor/students")
    assert page.status_code == 200 and b"/tutor/students/9" in page.data
    assert b"<b>Sample Student</b>" not in page.data and b"&lt;b&gt;Sample" in page.data


def test_empty_list_and_database_error(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "list_students", lambda tid: [])
    assert b"No students yet" in client.get("/tutor/students").data

    def broken(tid):
        raise RuntimeError("db down")
    monkeypatch.setattr(ps, "list_students", broken)
    assert b"Could not load your students" in client.get("/tutor/students").data


def student(shared):
    return {"id": 9, "full_name": "Sample Student", "course": "BSCS", "year_level": 2,
            "learning_goals": "Pass the exam" if shared else None, "shared": shared}


def test_a_student_who_is_not_yours_is_a_404(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    seen = {}
    monkeypatch.setattr(ps, "get_student", lambda tid, sid: seen.update(t=tid, s=sid))
    assert client.get("/tutor/students/9").status_code == 404 and seen == {"t": 1, "s": 9}


def test_without_consent_no_learning_data_is_loaded_or_shown(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "get_student", lambda tid, sid: student(False))
    monkeypatch.setattr(ps, "student_sessions", lambda tid, sid: [SESSION])
    monkeypatch.setattr(ps, "shared_summary", lambda sid: pytest.fail("must not load unshared data"))
    page = client.get("/tutor/students/9")
    assert page.status_code == 200 and b"has not shared" in page.data
    assert b"Pass the exam" not in page.data and b"Calculus 1" in page.data


def test_with_consent_the_summary_is_shown_and_escaped(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "get_student", lambda tid, sid: student(True))
    monkeypatch.setattr(ps, "student_sessions", lambda tid, sid: [SESSION])
    topic = {"topic_id": 1, "topic_name": "<i>Functions</i>", "subject_id": 4, "subject_name": "Python",
             "attempts": 3, "average": 50, "latest": 40, "trend": "declining", "status": "weak",
             "percents": [60, 50, 40]}
    monkeypatch.setattr(ps, "shared_summary", lambda sid: {
        "needs_work": [topic], "developing": [], "strong": [],
        "subjects": [{"id": 4, "name": "Python Programming", "category": "c", "done": 2, "total": 8, "percent": 25}]})
    page = client.get("/tutor/students/9")
    assert b"Needs work" in page.data and b"25%" in page.data and b"Pass the exam" in page.data
    assert b"<i>Functions</i>" not in page.data and b"&lt;i&gt;Functions" in page.data


def test_a_summary_failure_is_reported_not_shown_as_empty(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "get_student", lambda tid, sid: student(True))
    monkeypatch.setattr(ps, "student_sessions", lambda tid, sid: [])

    def broken(sid):
        raise RuntimeError("db down")
    monkeypatch.setattr(ps, "shared_summary", broken)
    assert b"could not be loaded" in client.get("/tutor/students/9").data


# ======================= the student's sharing choice =======================
def test_sharing_is_students_only_and_defaults_to_off(client, monkeypatch):
    assert client.get("/student/sharing").status_code == 302
    for role in ("tutor", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get("/student/sharing").status_code == 403
        assert client.post("/student/sharing", data={"share": "on"}).status_code == 403
    login_as(client, monkeypatch, "student")
    monkeypatch.setattr(ps, "get_sharing", lambda uid: False)
    page = client.get("/student/sharing")
    assert b"Sharing is off" in page.data and b"cannot</strong> see your AI tutor conversations" in page.data


def test_toggling_sharing_saves_and_is_audited(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    state, audits = {}, []
    monkeypatch.setattr(ps, "set_sharing", lambda uid, on: state.update(u=uid, on=on))
    monkeypatch.setattr(user_service, "log_audit", lambda *a, **k: audits.append(a))
    assert client.post("/student/sharing", data={"share": "on"}).status_code == 302
    assert state == {"u": 1, "on": True} and audits[-1][1] == "sharing_enabled"
    client.post("/student/sharing", data={})
    assert state["on"] is False and audits[-1][1] == "sharing_disabled"


# ======================= public profile =======================
def public_tutor(has_photo):
    return {"id": 5, "full_name": "Sample Tutor", "course": "BSCS", "year_level": 3, "bio": "Hi",
            "tutoring_format": "both", "skills": "Python, <b>Algebra</b>", "education": "BS Math <i>x</i>",
            "experience": "Two years", "has_photo": has_photo,
            "subjects": [{"name": "Calculus 1", "topics": None}],
            "availability": [{"day_name": "Monday", "label": "2:00 PM to 4:00 PM"}]}


def test_public_profile_shows_photo_skills_and_escapes_text(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(prog, "rating_summary", lambda tid: {"n": 0, "avg": None})
    monkeypatch.setattr(prog, "tutor_feedback", lambda tid, limit=5: [])
    monkeypatch.setattr(tutor_service, "get_public_tutor", lambda tid: public_tutor(1))
    page = client.get("/student/tutors/5")
    assert b"/media/tutors/5/photo" in page.data and b"Two years" in page.data and b"Skills" in page.data
    assert b"<b>Algebra</b>" not in page.data and b"&lt;b&gt;Algebra" in page.data
    monkeypatch.setattr(tutor_service, "get_public_tutor", lambda tid: public_tutor(0))
    assert b"/media/tutors/5/photo" not in client.get("/student/tutors/5").data
    assert b">ST</span>" in client.get("/student/tutors/5").data            # initials instead of a photo


# ======================= code hygiene =======================
def test_the_student_summary_code_never_touches_chats_or_answers():
    source = (ROOT / "app" / "services" / "people_service.py").read_text(encoding="utf-8")
    for word in ("ai_messages", "ai_conversations", "quiz_answers", "email"):
        assert word not in source


def test_the_tutor_queries_were_updated():
    source = (ROOT / "app" / "services" / "tutor_service.py").read_text(encoding="utf-8")
    assert source.count("AS has_photo") >= 2 and "tp.skills" in source


def test_the_photo_script_never_uses_innerhtml():
    script = (ROOT / "app" / "static" / "js" / "photo.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "eval("):
        assert banned not in script