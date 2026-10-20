"""Run with:  python -m pytest -v
Final safety net: checks EVERY route, every template and every file, so a forgotten
login check, an empty file or a doubled-up paste is caught immediately."""
import re
from datetime import date
from pathlib import Path

import pytest
import requests

from app import create_app, demo_data
from app.ai import ollama_client as oc
from app.services import user_service
from app.validators_tutor import parse_hhmm
from config import Config

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = {"main.home", "main.health", "main.about", "auth.login", "auth.register",
          "auth.logout", "static", "main.healthz"}
ACTION_VALUES = {"bookings.act": "accept", "admin.user_action": "activate",
                 "admin.feedback_action": "hide"}


class P10Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False
    OLLAMA_MODEL = "test-model"


@pytest.fixture
def app():
    return create_app(P10Config)


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


def all_routes(app):
    """(endpoint, method, url) for every non-public route."""
    adapter = app.url_map.bind("localhost")
    found = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC:
            continue
        values = {}
        for arg in rule.arguments:
            values[arg] = ACTION_VALUES[rule.endpoint] if arg == "action" else 1
        url = adapter.build(rule.endpoint, values)
        for method in sorted(rule.methods & {"GET", "POST"}):
            found.append((rule.endpoint, method, url))
    return found


# ======================= every route is protected =======================
def test_every_route_sends_anonymous_visitors_to_login(app, client):
    routes = all_routes(app)
    assert len(routes) > 50
    for endpoint, method, url in routes:
        response = client.open(url, method=method)
        assert response.status_code == 302 and "/login" in response.headers["Location"], \
            f"{method} {url} ({endpoint}) is not protected"


def allowed_roles(url):
    if url.startswith("/student/"):
        return {"student"}
    if url.startswith("/tutor/"):
        return {"tutor"}
    if url.startswith("/admin/"):
        return {"admin"}
    if url.startswith("/requests/"):
        return {"student", "tutor"}
    return None                      # any logged-in user (account, notifications)


def test_every_role_area_blocks_the_other_roles(app, client, monkeypatch):
    checked = {"student": 0, "tutor": 0, "admin": 0}
    for endpoint, method, url in all_routes(app):
        allowed = allowed_roles(url)
        if allowed is None:
            continue
        for role in ("student", "tutor", "admin"):
            if role in allowed:
                continue
            login_as(client, monkeypatch, role)
            response = client.open(url, method=method)
            assert response.status_code == 403, f"{role} can reach {method} {url} ({endpoint})"
            checked[role] += 1
    assert all(count > 20 for count in checked.values())


def test_about_page_is_public(client):
    response = client.get("/about")
    assert response.status_code == 200
    assert b"not an official website" in response.data and b"not saved" in response.data


# ======================= project hygiene =======================
def test_no_project_file_is_empty():
    empty = [str(p.relative_to(ROOT))
             for folder in ("app", "database", "tests")
             for p in (ROOT / folder).rglob("*")
             if p.is_file() and p.suffix in {".py", ".html", ".js", ".css", ".sql"}
             and p.name != "__init__.py" and p.stat().st_size == 0]
    assert empty == [], f"Empty files (paste the code again): {empty}"


def test_no_template_was_pasted_twice():
    doubled = [p.name for p in (ROOT / "app" / "templates").rglob("*.html")
               if p.read_text(encoding="utf-8").count("{% extends") > 1]
    assert doubled == []


def test_templates_do_nothing_the_security_policy_would_block():
    problems = []
    for path in (ROOT / "app" / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        is_email_template = path.is_relative_to(ROOT / "app" / "templates" / "emails")
        if re.search(r"<script(?![^>]*\bsrc=)", text):
            problems.append(f"{path.name}: inline <script>")
        if re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE):
            problems.append(f"{path.name}: inline event handler")
        if not is_email_template and re.search(r"\sstyle\s*=", text, re.IGNORECASE):
            problems.append(f"{path.name}: inline style attribute")
    assert problems == []


# ======================= AI thinking text =======================
class FakeReply:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def json(self):
        return {"message": {"role": "assistant", "content": self._content}}


def test_thinking_text_is_removed_from_ai_replies(app, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeReply("<think>hidden</think>\n\nThe answer."))
    with app.app_context():
        assert oc.chat([{"role": "user", "content": "hi"}]) == "The answer."


@pytest.mark.parametrize("content", ["<think>only thinking</think>", "<think>cut off mid-thought"])
def test_a_reply_with_only_thinking_is_rejected(app, monkeypatch, content):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeReply(content))
    with app.app_context(), pytest.raises(oc.OllamaBadResponse):
        oc.chat([])


# ======================= demonstration data =======================
def test_next_weekday():
    assert demo_data.next_weekday(date(2026, 9, 30), 0) == date(2026, 10, 5)     # Wed -> Monday
    assert demo_data.next_weekday(date(2026, 10, 5), 0) == date(2026, 10, 5)     # already Monday
    assert demo_data.next_weekday(date(2026, 9, 30), 2) == date(2026, 9, 30)


def test_demo_accounts_are_clearly_fictional():
    emails = [a["email"] for a in demo_data.ACCOUNTS]
    assert len(emails) == len(set(emails))
    for account in demo_data.ACCOUNTS:
        assert account["email"].startswith("demo.") and account["email"].endswith("@example.com")
        assert "Sample" in account["name"] and account["role"] in ("student", "tutor")
        assert "password" not in account                          # no password lives in the code


def test_the_sample_sessions_fit_the_sample_tutors_availability():
    start, end = (parse_hhmm(t) for t in demo_data.SESSION_TIME)
    monday = [s for s in demo_data.TUTOR_SETUP["tutor1"]["slots"] if s[0] == 0]
    assert any(parse_hhmm(a) <= start and parse_hhmm(b) >= end for _d, a, b in monday)
    wednesday = [s for s in demo_data.TUTOR_SETUP["tutor1"]["slots"] if s[0] == 2]
    assert any(parse_hhmm(a) <= parse_hhmm("10:00") and parse_hhmm(b) >= parse_hhmm("11:00")
               for _d, a, b in wednesday)


def test_one_demo_tutor_is_left_pending_on_purpose():
    approved = {key: setup["approved"] for key, setup in demo_data.TUTOR_SETUP.items()}
    assert approved == {"tutor1": True, "tutor2": True, "tutor3": False}
    tutor_keys = {a["key"] for a in demo_data.ACCOUNTS if a["role"] == "tutor"}
    assert tutor_keys == set(demo_data.TUTOR_SETUP)