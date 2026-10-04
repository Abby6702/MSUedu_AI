"""Run with:  python -m pytest -v   (MySQL and Ollama are faked.)"""
import pytest
from werkzeug.datastructures import MultiDict

from app import create_app
from app import validators_quiz as vq
from app.services import learning_service, profile_service as pf, quiz_generator, quiz_service
from app.services import ai_service, user_service
from app.ai import ollama_client as oc
from config import Config


class P12Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False
    OLLAMA_MODEL = "test-model"


@pytest.fixture
def app():
    return create_app(P12Config)


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


# ---------- rules ----------
@pytest.mark.parametrize("avg,latest,expected", [
    (90, 88, "strong"), (75, 75, "strong"), (80, 74, "developing"), (70, 65, "developing"),
    (59, 90, "weak"), (77, 55, "weak"), (40, 40, "weak"), (60, 60, "developing")])
def test_classification(avg, latest, expected):
    assert pf.classify(avg, latest) == expected


def test_trend():
    assert pf.trend([50]) == "new"
    assert pf.trend([60, 75]) == "improving" and pf.trend([80, 65]) == "declining"
    assert pf.trend([70, 74]) == "steady"


def attempt(topic_id, name, score, total, subject_id=4):
    return {"topic_id": topic_id, "topic_name": name, "subject_id": subject_id,
            "subject_name": "Python Programming", "score": score, "total": total}


def test_the_spec_example_is_detected_as_weak():
    """Quiz scores 90, 85, 55 on the same topic: a possible weakness."""
    rows = [attempt(1, "Functions", 9, 10), attempt(1, "Functions", 17, 20), attempt(1, "Functions", 11, 20)]
    t = pf.summarize_topics(rows)[0]
    assert t["percents"] == [90, 85, 55] and t["average"] == 77
    assert t["latest"] == 55 and t["trend"] == "declining" and t["status"] == "weak"


def test_topics_are_grouped_and_weakest_first():
    rows = [attempt(1, "Variables", 10, 10), attempt(2, "Lists", 3, 10), attempt(1, "Variables", 9, 10)]
    topics = pf.summarize_topics(rows)
    assert [t["topic_name"] for t in topics] == ["Lists", "Variables"]
    assert topics[1]["attempts"] == 2 and topics[1]["status"] == "strong"
    assert pf.summarize_topics([]) == [] and pf.pct(0, 0) == 0


# ---------- quiz form validation ----------
TOPICS = {7: {"subject_id": 4, "name": "Functions"}, 8: {"subject_id": 9, "name": "Vectors"}}


def form(**changes):
    base = {"subject_id": "4", "topic": "", "topic_id": "7", "difficulty": "easy", "count": "5",
            "types": ["mcq"], "mode": "practice"}
    base.update(changes)
    return MultiDict(base)


def test_blank_topic_text_uses_the_lesson_topic_name():
    data, errors = vq.validate_generate_form(form(), {4}, TOPICS)
    assert errors == [] and data["topic_id"] == 7 and data["topic"] == "Functions"


def test_typed_topic_text_is_kept():
    data, _ = vq.validate_generate_form(form(topic="parameters and return"), {4}, TOPICS)
    assert data["topic"] == "parameters and return" and data["topic_id"] == 7


@pytest.mark.parametrize("topic_id", ["8", "999", "abc"])
def test_a_topic_from_another_subject_or_unknown_is_rejected(topic_id):
    data, errors = vq.validate_generate_form(form(topic_id=topic_id, topic="x" * 5), {4}, TOPICS)
    if topic_id == "abc":                       # not a number: treated as "no topic chosen"
        assert data["topic_id"] is None
    else:
        assert errors and data["topic_id"] is None


def test_the_old_form_still_works_without_a_topic_list():
    data, errors = vq.validate_generate_form(form(topic_id="", topic="Limits"), {4})
    assert errors == [] and data["topic_id"] is None


# ---------- linking ----------
def test_generator_links_the_topic_after_saving(app, monkeypatch):
    monkeypatch.setattr(ai_service, "_rate_limited", lambda uid: False)
    monkeypatch.setattr(ai_service, "_log_usage", lambda *a, **k: None)
    payload = ('{"questions":[{"type":"tf","question":"A constant has derivative zero.",'
               '"answer":true,"explanation":"It never changes."}]}')
    monkeypatch.setattr(oc, "chat", lambda messages, **k: payload)
    monkeypatch.setattr(quiz_service, "create_quiz", lambda *a, **k: 9)
    linked = {}
    monkeypatch.setattr(quiz_service, "link_topic", lambda q, u, t: linked.update(q=q, u=u, t=t))
    data = {"subject_id": 4, "topic_id": 7, "topic": "Functions", "difficulty": "easy",
            "count": 1, "types": ["tf"], "mode": "practice"}
    with app.app_context():
        status, body = quiz_generator.generate_quiz(1, 4, "Python Programming", data)
    assert status == 200 and linked == {"q": 9, "u": 1, "t": 7}


def test_a_failed_link_does_not_lose_the_quiz(app, monkeypatch):
    monkeypatch.setattr(ai_service, "_rate_limited", lambda uid: False)
    monkeypatch.setattr(ai_service, "_log_usage", lambda *a, **k: None)
    monkeypatch.setattr(oc, "chat", lambda messages, **k: (
        '{"questions":[{"type":"tf","question":"A constant has derivative zero.",'
        '"answer":true,"explanation":"It never changes."}]}'))
    monkeypatch.setattr(quiz_service, "create_quiz", lambda *a, **k: 9)

    def broken(q, u, t):
        raise RuntimeError("db down")
    monkeypatch.setattr(quiz_service, "link_topic", broken)
    data = {"subject_id": 4, "topic_id": 7, "topic": "Functions", "difficulty": "easy",
            "count": 1, "types": ["tf"], "mode": "practice"}
    with app.app_context():
        assert quiz_generator.generate_quiz(1, 4, "Python Programming", data)[0] == 200


# ---------- routes ----------
PROFILE = {"lessons_done": 3, "lessons_total": 8, "progress_percent": 38, "streak": 2,
           "study_minutes": 20, "quiz_attempts": 3, "quiz_average": 77, "sessions_completed": 1,
           "ai_questions": 4,
           "strong": [], "developing": [],
           "weak": [{"topic_id": 1, "topic_name": "<b>Functions</b>", "subject_id": 4,
                     "subject_name": "Python Programming", "attempts": 3, "average": 77, "latest": 55,
                     "trend": "declining", "status": "weak", "percents": [90, 85, 55]}],
           "topics": [{"topic_id": 1, "topic_name": "<b>Functions</b>", "subject_id": 4,
                       "subject_name": "Python Programming", "attempts": 3, "average": 77, "latest": 55,
                       "trend": "declining", "status": "weak", "percents": [90, 85, 55]}]}


def test_profile_is_students_only(client, monkeypatch):
    assert client.get("/student/learning/profile").status_code == 302
    for role in ("tutor", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get("/student/learning/profile").status_code == 403


def test_profile_page_shows_the_data_and_the_caveat(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(pf, "build_profile", lambda uid: PROFILE)
    page = client.get("/student/learning/profile")
    assert page.status_code == 200 and b"does not prove" in page.data
    assert b"Needs work" in page.data and b"77%" in page.data
    assert b"<b>Functions</b>" not in page.data and b"&lt;b&gt;Functions" in page.data


def test_profile_with_no_quiz_data_shows_an_empty_state(client, monkeypatch):
    login_as(client, monkeypatch)
    empty = dict(PROFILE, strong=[], developing=[], weak=[], topics=[], quiz_average=None, quiz_attempts=0)
    monkeypatch.setattr(pf, "build_profile", lambda uid: empty)
    assert b"No topic results yet" in client.get("/student/learning/profile").data


def test_profile_survives_a_database_error(client, monkeypatch):
    login_as(client, monkeypatch)

    def broken(uid):
        raise RuntimeError("db down")
    monkeypatch.setattr(pf, "build_profile", broken)
    page = client.get("/student/learning/profile")
    assert page.status_code == 200 and b"Could not load your learning profile" in page.data


def test_the_quiz_page_still_loads_if_topics_fail(client, monkeypatch):
    from app.services import subject_service
    login_as(client, monkeypatch)
    monkeypatch.setattr(subject_service, "list_subjects", lambda active_only=True: [
        {"id": 4, "name": "Python Programming", "category": "Computing", "is_active": 1}])
    monkeypatch.setattr(quiz_service, "list_quizzes", lambda uid: [])

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(learning_service, "list_topics", broken)
    assert client.get("/student/quizzes/").status_code == 200


def test_the_quiz_page_offers_lesson_topics(client, monkeypatch):
    from app.services import subject_service
    login_as(client, monkeypatch)
    monkeypatch.setattr(subject_service, "list_subjects", lambda active_only=True: [
        {"id": 4, "name": "Python Programming", "category": "Computing", "is_active": 1}])
    monkeypatch.setattr(quiz_service, "list_quizzes", lambda uid: [])
    monkeypatch.setattr(learning_service, "list_topics", lambda: [
        {"id": 7, "subject_id": 4, "name": "Functions", "level": 3, "subject_name": "Python Programming"}])
    assert b"Python Programming: Functions" in client.get("/student/quizzes/").data