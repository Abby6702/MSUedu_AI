"""Run with:  python -m pytest -v   (MySQL is faked.)"""
from datetime import date, datetime
from pathlib import Path

import pytest

from app import create_app
from app.services import learning_service as ls
from app.services import user_service
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P11Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def client():
    return create_app(P11Config).test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


# ---------- rules ----------
def test_percent():
    assert ls.percent(1, 3) == 33 and ls.percent(0, 0) == 0 and ls.percent(8, 8) == 100


def test_streak_rules():
    today = date(2026, 10, 5)
    d = lambda n: date(2026, 10, n)
    assert ls.compute_streak(set(), today) == 0
    assert ls.compute_streak({d(5), d(4), d(3)}, today) == 3
    assert ls.compute_streak({d(4), d(3)}, today) == 2          # nothing yet today: still alive
    assert ls.compute_streak({d(2), d(1)}, today) == 0          # broken
    assert ls.compute_streak({d(5), d(3)}, today) == 1          # a gap ends the run


def row(topic_id, name, level, lesson_id, done):
    return {"topic_id": topic_id, "topic_name": name, "level": level, "position": 1,
            "lesson_id": lesson_id, "title": f"Lesson {lesson_id}", "difficulty": "easy",
            "minutes": 5, "completed": done}


def test_build_path_groups_levels_and_finds_the_next_lesson():
    path = ls.build_path([row(1, "Variables", 1, 10, 1), row(2, "Data Types", 1, 11, 0),
                          row(3, "Loops", 2, 12, 0)])
    assert [lv["level"] for lv in path["levels"]] == [1, 2]
    assert path["done"] == 1 and path["total"] == 3 and path["percent"] == 33
    assert path["next"]["id"] == 11 and path["levels"][0]["done"] == 1


def test_a_finished_or_empty_path_has_no_next_lesson():
    assert ls.build_path([row(1, "Variables", 1, 10, 1)])["next"] is None
    empty = ls.build_path([])
    assert empty["total"] == 0 and empty["percent"] == 0 and empty["levels"] == []


def test_the_seed_file_is_complete_and_safe():
    sql = (ROOT / "database" / "schema_phase11.sql").read_text(encoding="utf-8")
    assert sql.count("INSERT IGNORE INTO topics") == 8
    assert sql.count("INSERT IGNORE INTO lessons") == 8
    assert "DROP " not in sql.upper()


# ---------- routes ----------
LESSON = {"id": 10, "title": "Variables", "body": "<script>alert(1)</script> x = 1", "difficulty": "easy",
          "minutes": 5, "topic_id": 1, "topic_name": "Variables", "level": 1, "subject_id": 4,
          "subject_name": "Python Programming", "completed": 0}


@pytest.mark.parametrize("path", ["/student/learning/", "/student/learning/4", "/student/learning/lessons/10"])
def test_anonymous_and_other_roles_are_blocked(client, monkeypatch, path):
    assert client.get(path).status_code == 302
    for role in ("tutor", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get(path).status_code == 403


def test_index_page_shows_progress(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ls, "list_learning_subjects", lambda uid: [
        {"id": 4, "name": "Python Programming", "category": "Computing", "total": 8, "done": 2, "percent": 25}])
    monkeypatch.setattr(ls, "overall_stats", lambda uid: {"completed": 2, "streak": 3})
    page = client.get("/student/learning/")
    assert page.status_code == 200 and b"Python Programming" in page.data
    assert b"Day learning streak" in page.data and b"Continue" in page.data


def test_path_page(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ls, "get_subject", lambda sid: {"id": 4, "name": "Python Programming", "category": "Computing"})
    monkeypatch.setattr(ls, "path_rows", lambda uid, sid: [row(1, "Variables", 1, 10, 1), row(2, "Data Types", 1, 11, 0)])
    page = client.get("/student/learning/4")
    assert page.status_code == 200 and b"Data Types" in page.data and b"Up next" in page.data


def test_unknown_subject_and_lesson_are_404(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ls, "get_subject", lambda sid: None)
    monkeypatch.setattr(ls, "get_lesson", lambda lid, uid: None)
    assert client.get("/student/learning/99").status_code == 404
    assert client.get("/student/learning/lessons/99").status_code == 404
    assert client.post("/student/learning/lessons/99/complete").status_code == 404


def test_lesson_text_is_escaped(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ls, "get_lesson", lambda lid, uid: dict(LESSON))
    page = client.get("/student/learning/lessons/10")
    assert page.status_code == 200 and b"<script>alert(1)</script>" not in page.data
    assert b"&lt;script&gt;" in page.data and b"Mark as complete" in page.data


def test_completing_a_lesson_saves_for_the_logged_in_student(client, monkeypatch):
    login_as(client, monkeypatch)
    saved = {}
    monkeypatch.setattr(ls, "get_lesson", lambda lid, uid: dict(LESSON))
    monkeypatch.setattr(ls, "mark_complete", lambda uid, lid: saved.update(u=uid, l=lid) or True)
    response = client.post("/student/learning/lessons/10/complete")
    assert response.status_code == 302 and response.headers["Location"].endswith("/student/learning/4")
    assert saved == {"u": 1, "l": 10}                      # the user id comes from the login


def test_a_completed_lesson_hides_the_button(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ls, "get_lesson", lambda lid, uid: dict(LESSON, completed=1))
    assert b"Mark as complete" not in client.get("/student/learning/lessons/10").data


def test_a_save_failure_is_reported(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ls, "get_lesson", lambda lid, uid: dict(LESSON))

    def broken(uid, lid):
        raise RuntimeError("db down")
    monkeypatch.setattr(ls, "mark_complete", broken)
    page = client.post("/student/learning/lessons/10/complete", follow_redirects=True)
    assert b"Could not save your progress" in page.data