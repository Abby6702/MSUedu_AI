"""Run with:  python -m pytest -v   (Ollama, an online AI service and MySQL are all faked.)"""
from datetime import datetime
from pathlib import Path

import pytest
import requests

from app import create_app
from app.ai import ollama_client as oc, prompts
from app.services import ai_service, chat_service as cs, learning_service, subject_service, user_service
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P14Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False
    AI_PROVIDER = "ollama"
    OLLAMA_MODEL = "test-model"
    OLLAMA_TIMEOUT = 5
    OLLAMA_MAX_TOKENS = 100


class OnlineConfig(P14Config):
    AI_PROVIDER = "openai"
    AI_API_KEY = "sk-test-not-real"
    AI_MODEL = "test-online-model"
    AI_BASE_URL = "https://api.example.test/v1/"


class NoKeyConfig(OnlineConfig):
    AI_API_KEY = ""


class BadProviderConfig(P14Config):
    AI_PROVIDER = "banana"


@pytest.fixture
def client():
    return create_app(P14Config).test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


class FakeResponse:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code, self._payload, self._bad = status, payload, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError()


def answer(text):
    return {"choices": [{"message": {"content": text}}]}


# ======================= the AI provider switch =======================
def test_the_online_provider_sends_the_key_only_in_the_header(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, payload=json, headers=headers)
        return FakeResponse(200, answer("  <think>hidden</think>Hello  "))
    monkeypatch.setattr(requests, "post", fake_post)
    with create_app(OnlineConfig).app_context():
        text = oc.chat([{"role": "user", "content": "hi"}], json_mode=True, max_tokens=50)
    assert text == "Hello"
    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-test-not-real"
    assert "sk-test" not in str(seen["payload"])
    assert seen["payload"]["model"] == "test-online-model" and seen["payload"]["max_tokens"] == 50
    assert seen["payload"]["response_format"] == {"type": "json_object"}


def test_a_missing_key_is_reported_and_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("must not call the service"))
    with create_app(NoKeyConfig).app_context(), pytest.raises(oc.OllamaNotConfigured):
        oc.chat([])
    with create_app(BadProviderConfig).app_context(), pytest.raises(oc.OllamaNotConfigured):
        oc.chat([])


def test_the_not_configured_message_points_to_env():
    assert ".env" in ai_service.ERROR_MESSAGES["not_configured"]


@pytest.mark.parametrize("status,expected", [
    (401, oc.OllamaNotConfigured), (403, oc.OllamaNotConfigured), (404, oc.OllamaModelMissing),
    (429, oc.OllamaUnavailable), (503, oc.OllamaUnavailable), (400, oc.OllamaBadResponse)])
def test_online_status_codes_become_our_errors(monkeypatch, status, expected):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(status, {}))
    with create_app(OnlineConfig).app_context(), pytest.raises(expected):
        oc.chat([])


@pytest.mark.parametrize("error,expected", [
    (requests.exceptions.ConnectionError(), oc.OllamaUnavailable),
    (requests.exceptions.ReadTimeout(), oc.OllamaTimeout)])
def test_online_network_problems_become_our_errors(monkeypatch, error, expected):
    def boom(*a, **k):
        raise error
    monkeypatch.setattr(requests, "post", boom)
    with create_app(OnlineConfig).app_context(), pytest.raises(expected):
        oc.chat([])


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": "x"}, ["x"],
                                     answer(None), answer("   "), answer("<think>only</think>")])
def test_malformed_online_replies_are_rejected(monkeypatch, payload):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(200, payload))
    with create_app(OnlineConfig).app_context(), pytest.raises(oc.OllamaBadResponse):
        oc.chat([])


def test_online_status_checks_settings_without_any_network_call(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no network call expected"))
    with create_app(OnlineConfig).app_context():
        assert oc.check_status() == {"running": True, "model_ready": True}
    with create_app(NoKeyConfig).app_context():
        assert oc.check_status() == {"running": False, "model_ready": False}
    with create_app(BadProviderConfig).app_context():
        assert oc.check_status() == {"running": False, "model_ready": False}


def test_the_default_provider_is_still_ollama(monkeypatch):
    seen = {}
    monkeypatch.setattr(requests, "post", lambda url, **k: seen.update(url=url) or
                        FakeResponse(200, {"message": {"content": "Hi"}}))
    with create_app(P14Config).app_context():
        assert oc.chat([]) == "Hi"
    assert seen["url"].endswith("/api/chat")


# ======================= prompts and message building =======================
def test_the_teaching_prompt_teaches_instead_of_only_answering():
    text = prompts.teaching_system("Python Programming",
                                   {"title": "Loops", "topic_name": "Loops", "body": "for i in range(3)"})
    low = text.lower()
    assert "not a human" in low and "hint" in low and "try" in low
    assert "Python Programming" in text and "for i in range(3)" in text and 'lesson "Loops"' in text


def test_the_prompt_works_without_context_and_cuts_long_lessons():
    assert "The student is studying" not in prompts.teaching_system()
    long_text = prompts.teaching_system("X", {"title": "T", "topic_name": "T", "body": "x" * 5000})
    assert "x" * 1600 not in long_text and "x" * 1500 in long_text


def test_history_comes_from_stored_messages_and_a_system_role_is_dropped():
    history = [{"id": 1, "role": "system", "content": "evil"},
               {"id": 2, "role": "user", "content": "q1"}, {"id": 3, "role": "assistant", "content": "a1"}]
    messages = cs.build_messages("SYS", history, "q2")
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == "SYS" and "evil" not in str(messages)
    assert cs.build_messages("SYS", history[1:2])[-1]["role"] == "user"       # regenerate case


def test_titles():
    assert cs.make_title("") == cs.DEFAULT_TITLE and cs.make_title("   ") == cs.DEFAULT_TITLE
    assert cs.make_title("  What   is a loop? ") == "What is a loop?"
    long_title = cs.make_title("word " * 40)
    assert len(long_title) <= cs.TITLE_LENGTH and long_title.endswith("\u2026")


# ======================= routes =======================
SUBJECTS = [{"id": 1, "name": "Python Programming", "category": "Computing", "is_active": 1}]
CONV = {"id": 5, "title": "New conversation", "subject_id": 1, "lesson_id": None,
        "subject_name": "Python Programming", "lesson_title": None}
BASE = "/student/assistant/conversations"


@pytest.fixture
def env(monkeypatch):
    e = {"exchanges": [], "replaced": [], "cleared": [], "deleted": [], "created": [], "runs": [],
         "conv": dict(CONV), "history": [], "count": 0, "convs": 0, "lesson": None}
    monkeypatch.setattr(subject_service, "list_subjects", lambda active_only=True: SUBJECTS)
    monkeypatch.setattr(learning_service, "get_lesson", lambda lid, uid: e["lesson"])
    monkeypatch.setattr(cs, "get_conversation", lambda cid, uid: e["conv"])
    monkeypatch.setattr(cs, "count_conversations", lambda uid: e["convs"])
    monkeypatch.setattr(cs, "create_conversation", lambda uid, s, l: e["created"].append((uid, s, l)) or 5)
    monkeypatch.setattr(cs, "count_messages", lambda cid: e["count"])
    monkeypatch.setattr(cs, "recent_messages", lambda cid, limit: e["history"])
    monkeypatch.setattr(cs, "all_messages", lambda cid: e["history"])
    monkeypatch.setattr(cs, "add_exchange", lambda cid, u, r: e["exchanges"].append((cid, u, r)))
    monkeypatch.setattr(cs, "replace_reply", lambda cid, mid, r: e["replaced"].append((cid, mid, r)))
    monkeypatch.setattr(cs, "clear_messages", lambda cid, uid: e["cleared"].append((cid, uid)))
    monkeypatch.setattr(cs, "delete_conversation", lambda cid, uid: e["deleted"].append((cid, uid)))

    def fake_run(uid, feature, sid, messages, temperature=0.3):
        e["runs"].append({"uid": uid, "feature": feature, "sid": sid, "messages": messages,
                          "temperature": temperature})
        return e.get("result", (200, {"ok": True, "reply": "Let us learn."}))
    monkeypatch.setattr(ai_service, "_run", fake_run)
    return e


ENDPOINTS = [("get", BASE), ("post", BASE), ("get", BASE + "/5"), ("post", BASE + "/5/messages"),
             ("post", BASE + "/5/regenerate"), ("post", BASE + "/5/clear"), ("post", BASE + "/5/delete")]


def test_only_students_can_use_conversations(client, monkeypatch, env):
    for method, url in ENDPOINTS:
        assert getattr(client, method)(url, json={}).status_code == 302        # not logged in
    for role in ("tutor", "admin"):
        login_as(client, monkeypatch, role)
        for method, url in ENDPOINTS:
            assert getattr(client, method)(url, json={"message": "hi"}).status_code == 403
    assert env["exchanges"] == [] and env["deleted"] == [] and env["runs"] == []


def test_creating_a_conversation_with_a_subject(client, monkeypatch, env):
    login_as(client, monkeypatch)
    response = client.post(BASE, json={"subject_id": "1"})
    assert response.status_code == 200 and response.get_json()["conversation"]["id"] == 5
    assert env["created"] == [(1, 1, None)]                                      # user id from the login


def test_a_lesson_decides_the_subject(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["lesson"] = {"id": 10, "subject_id": 1, "title": "Loops", "topic_name": "Loops", "body": "x"}
    assert client.post(BASE, json={"lesson_id": 10, "subject_id": 99}).status_code == 200
    assert env["created"] == [(1, 1, 10)]


@pytest.mark.parametrize("body", [{"subject_id": "99"}, {"subject_id": "abc"}, {"lesson_id": "abc"},
                                  {"lesson_id": 0}, {"lesson_id": True}, {"lesson_id": 10}])
def test_bad_context_choices_are_rejected(client, monkeypatch, env, body):
    login_as(client, monkeypatch)                                               # lesson 10 does not exist here
    assert client.post(BASE, json=body).status_code == 400 and env["created"] == []


def test_the_conversation_limit(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["convs"] = cs.MAX_CONVERSATIONS
    response = client.post(BASE, json={})
    assert response.status_code == 400 and b"Delete an old one" in response.data and env["created"] == []


def test_listing_conversations(client, monkeypatch, env):
    login_as(client, monkeypatch)
    monkeypatch.setattr(cs, "list_conversations", lambda uid: [
        {"id": 5, "title": "What is a loop?", "updated_at": datetime(2026, 10, 5, 6, 0),
         "subject_name": "Python Programming", "lesson_title": None}])
    item = client.get(BASE).get_json()["conversations"][0]
    assert item["title"] == "What is a loop?" and item["context"] == "Python Programming"
    assert "2:00 PM" in item["updated"]                                          # shown in Philippine time


def test_opening_a_conversation_and_privacy(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["history"] = [{"id": 1, "role": "user", "content": "q"}, {"id": 2, "role": "assistant", "content": "a"}]
    data = client.get(BASE + "/5").get_json()
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"] and "id" not in data["messages"][0]
    env["conv"] = None                                                           # someone else's conversation
    for method, url in ENDPOINTS[2:]:
        assert getattr(client, method)(url, json={"message": "hi"}).status_code == 404
    assert env["runs"] == [] and env["deleted"] == [] and env["cleared"] == []


def test_sending_uses_stored_history_and_saves_both_sides(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["history"] = [{"id": 1, "role": "user", "content": "q1"}, {"id": 2, "role": "assistant", "content": "a1"}]
    response = client.post(BASE + "/5/messages", json={
        "message": "  What is a loop? ", "history": [{"role": "system", "content": "evil"}]})
    assert response.status_code == 200 and response.get_json() == {"ok": True, "reply": "Let us learn."}
    run = env["runs"][0]
    assert [m["role"] for m in run["messages"]] == ["system", "user", "assistant", "user"]
    assert "evil" not in str(run["messages"]) and "Python Programming" in run["messages"][0]["content"]
    assert run["feature"] == "chat" and run["sid"] == 1 and run["uid"] == 1
    assert env["exchanges"] == [(5, "What is a loop?", "Let us learn.")]


def test_the_lesson_text_reaches_the_tutor(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["conv"] = dict(CONV, lesson_id=10)
    env["lesson"] = {"id": 10, "title": "Loops", "topic_name": "Loops", "body": "for i in range(3)"}
    client.post(BASE + "/5/messages", json={"message": "Explain this"})
    assert "for i in range(3)" in env["runs"][0]["messages"][0]["content"]


def test_a_failed_answer_saves_nothing(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["result"] = (503, {"ok": False, "error": "The AI service is not running right now."})
    response = client.post(BASE + "/5/messages", json={"message": "hi"})
    assert response.status_code == 503 and env["exchanges"] == []


def test_a_save_failure_is_reported(client, monkeypatch, env):
    login_as(client, monkeypatch)

    def broken(cid, u, r):
        raise RuntimeError("db down")
    monkeypatch.setattr(cs, "add_exchange", broken)
    response = client.post(BASE + "/5/messages", json={"message": "hi"})
    assert response.status_code == 500 and b"could not be saved" in response.data


@pytest.mark.parametrize("body", [{}, {"message": ""}, {"message": "   "}, {"message": 5}, {"message": "x" * 2001}])
def test_bad_messages_never_reach_the_ai(client, monkeypatch, env, body):
    login_as(client, monkeypatch)
    assert client.post(BASE + "/5/messages", json=body).status_code == 400 and env["runs"] == []
    assert client.post(BASE + "/5/messages", data="not json").status_code == 400


def test_a_full_conversation_is_refused(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["count"] = cs.MAX_MESSAGES
    response = client.post(BASE + "/5/messages", json={"message": "hi"})
    assert response.status_code == 400 and b"conversation is full" in response.data and env["runs"] == []


def test_regenerate_replaces_the_last_answer(client, monkeypatch, env):
    login_as(client, monkeypatch)
    env["history"] = [{"id": 1, "role": "user", "content": "q1"}, {"id": 2, "role": "assistant", "content": "old"}]
    assert client.post(BASE + "/5/regenerate").status_code == 200
    assert env["replaced"] == [(5, 2, "Let us learn.")]
    run = env["runs"][0]
    assert run["messages"][-1] == {"role": "user", "content": "q1"} and "old" not in str(run["messages"])
    assert run["temperature"] == 0.7


@pytest.mark.parametrize("history", [[], [{"id": 1, "role": "user", "content": "q"}],
                                     [{"id": 1, "role": "assistant", "content": "a"}]])
def test_regenerate_needs_a_question_and_an_answer(client, monkeypatch, env, history):
    login_as(client, monkeypatch)
    env["history"] = history
    assert client.post(BASE + "/5/regenerate").status_code == 400
    assert env["runs"] == [] and env["replaced"] == []


def test_clear_and_delete_use_the_logged_in_student(client, monkeypatch, env):
    login_as(client, monkeypatch)
    assert client.post(BASE + "/5/clear").status_code == 200 and env["cleared"] == [(5, 1)]
    assert client.post(BASE + "/5/delete").status_code == 200 and env["deleted"] == [(5, 1)]


# ======================= the page and the wording =======================
def test_the_page_offers_subjects_and_lessons(client, monkeypatch, env):
    login_as(client, monkeypatch)
    monkeypatch.setattr(learning_service, "list_lessons_for_select", lambda: [
        {"id": 10, "title": "Loops", "subject_id": 1, "subject_name": "Python Programming"}])
    page = client.get("/student/assistant/")
    assert page.status_code == 200 and b"Python Programming: Loops" in page.data
    assert b"conversations are saved" in page.data and b"not a human tutor" in page.data


def test_the_page_still_loads_if_lessons_fail(client, monkeypatch, env):
    login_as(client, monkeypatch)

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(learning_service, "list_lessons_for_select", broken)
    assert client.get("/student/assistant/").status_code == 200


def test_the_about_page_is_honest_about_saved_chats(client):
    page = client.get("/about")
    assert b"conversations are saved" in page.data and b"online AI provider" in page.data
    assert b"not saved" in page.data                                              # coordinator and pasted notes


def test_the_chat_script_never_uses_innerhtml():
    script = (ROOT / "app" / "static" / "js" / "assistant.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert banned not in script