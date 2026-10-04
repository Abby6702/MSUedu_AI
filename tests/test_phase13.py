"""Run with:  python -m pytest -v   (MySQL is faked; the rules need no database at all.)"""
import json
import pytest

from app import create_app
from app.services import learning_agent as la
from app.services import learning_service, profile_service as pf
from app.services import quiz_service, recommendation_service as rs, subject_service, user_service
from config import Config


class P13Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


class LiveConfig(P13Config):
    TESTING = False           # to test the real safe_run behaviour


@pytest.fixture
def app():
    return create_app(P13Config)


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


def topic(percents, tid=1, sid=4, name="Functions"):
    rows = [{"topic_id": tid, "topic_name": name, "subject_id": sid, "subject_name": "Python Programming",
             "score": p, "total": 100} for p in percents]
    return pf.summarize_topics(rows)[0]


OPEN = {"total": 3, "done": 1, "next": {"id": 21, "title": "Functions: reusable blocks", "topic": "Functions"}}
DONE = {"total": 3, "done": 3, "next": None}


# ======================= the rules =======================
def test_helpers():
    assert la.trailing_weak([90, 50, 40]) == 2 and la.trailing_weak([50, 90]) == 0 and la.trailing_weak([]) == 0
    assert [la.recommend_difficulty(x) for x in (40, 50, 74, 75, 95)] == ["easy", "medium", "medium", "hard", "hard"]


def test_the_spec_example_recommends_a_review_first():
    rec = la.decide_topic(topic([90, 85, 55]), OPEN)
    assert rec["kind"] == "review_lesson" and rec["lesson_id"] == 21 and rec["key"] == "t1"
    assert rec["reasoning"]["rule"] == "R1_review"
    assert "90%, 85%, 55%" in rec["reasoning"]["steps"][0]
    assert rec["reasoning"]["facts"]["latest"] == 55


def test_after_the_review_it_recommends_practice_at_a_fitting_level():
    rec = la.decide_topic(topic([90, 85, 55]), DONE)
    assert rec["kind"] == "practice" and rec["difficulty"] == "medium"
    assert la.decide_topic(topic([40]), DONE)["difficulty"] == "easy"


def test_persistent_weakness_after_review_recommends_a_human_tutor():
    rec = la.decide_topic(topic([50, 45, 40]), DONE)
    assert rec["kind"] == "human_tutor" and rec["reasoning"]["facts"]["weak_run"] == 3
    assert "not a diagnosis" in rec["message"]


def test_the_tutor_is_not_suggested_before_the_review_is_done():
    assert la.decide_topic(topic([50, 45, 40]), OPEN)["kind"] == "review_lesson"
    assert la.decide_topic(topic([50, 50, 50, 50, 50]), OPEN)["kind"] == "human_tutor"   # 5 in a row


def test_escalation_is_gradual():
    assert la.decide_topic(topic([40, 40]), DONE)["kind"] == "practice"        # only 2 in a row
    assert la.decide_topic(topic([40, 40, 40]), DONE)["kind"] == "human_tutor"


def test_topics_without_lessons_skip_the_review():
    none = {"total": 0, "done": 0, "next": None}
    assert la.decide_topic(topic([40]), none)["kind"] == "practice"
    assert la.decide_topic(topic([40, 40, 40]), None)["kind"] == "human_tutor"


def test_no_recommendation_when_strong_or_evidence_is_thin():
    assert la.decide_topic(topic([90, 88]), DONE) is None
    assert la.decide_topic(topic([70]), OPEN) is None                          # one developing quiz
    assert la.decide_topic(topic([70, 68]), DONE)["kind"] == "practice"        # two: enough
    assert la.decide_topic(topic([70, 68]), OPEN)["kind"] == "review_lesson"


def test_a_recent_drop_is_caught_even_with_a_good_average():
    rec = la.decide_topic(topic([100, 95, 50]), DONE)
    assert rec["reasoning"]["facts"]["status"] == "weak"


# ======================= all topics together =======================
LESSON_ROWS = [
    {"topic_id": 1, "subject_id": 4, "topic_name": "Variables", "subject_name": "Python", "lesson_id": 10,
     "title": "Variables", "completed": 1},
    {"topic_id": 2, "subject_id": 4, "topic_name": "Functions", "subject_name": "Python", "lesson_id": 11,
     "title": "Functions", "completed": 0},
    {"topic_id": 2, "subject_id": 4, "topic_name": "Functions", "subject_name": "Python", "lesson_id": 12,
     "title": "Parameters", "completed": 0}]


def test_lessons_are_indexed_with_the_first_unfinished_one_next():
    by_topic, by_subject = la.index_lessons(LESSON_ROWS)
    assert by_topic[2]["next"]["id"] == 11 and by_topic[2]["total"] == 2 and by_topic[1]["next"] is None
    assert by_subject[4]["done"] == 1 and by_subject[4]["next"]["title"] == "Functions"


def test_next_lesson_appears_only_for_started_subjects_without_weak_topics():
    by_topic, by_subject = la.index_lessons(LESSON_ROWS)
    recs = la.decide_all([], by_topic, by_subject)
    assert [r["kind"] for r in recs] == ["next_lesson"] and recs[0]["lesson_id"] == 11
    weak = topic([30, 30], tid=2, sid=4, name="Functions")
    assert all(r["kind"] != "next_lesson" for r in la.decide_all([weak], by_topic, by_subject))
    untouched = {4: dict(by_subject[4], done=0)}
    assert la.decide_all([], by_topic, untouched) == []


def test_recommendations_are_ordered_by_urgency():
    by_topic = {1: DONE, 2: OPEN}
    topics = [topic([70, 68], tid=1, name="Loops"), topic([40, 40, 40], tid=3, name="Lists"),
              topic([40], tid=2, name="Functions")]
    by_topic[3] = DONE
    kinds = [r["kind"] for r in la.decide_all(topics, by_topic, {})]
    assert kinds == ["human_tutor", "review_lesson", "practice"]


# ======================= keeping stored recommendations in step =======================
def rec(key="t1", kind="review_lesson", evidence=4):
    return {"key": key, "kind": kind, "evidence": evidence}


def test_plan_inserts_new_updates_same_and_replaces_changed():
    assert la.plan_sync({}, [rec()])["insert"] == [rec()]
    e = {"t1": {"id": 5, "kind": "review_lesson", "status": "active", "evidence": 4}}
    plan = la.plan_sync(e, [rec()])
    assert plan["update"] == [(5, rec())] and plan["insert"] == [] and plan["retire"] == []
    plan = la.plan_sync(e, [rec(kind="practice")])
    assert plan["retire"] == [(5, "superseded")] and plan["insert"] == [rec(kind="practice")]


def test_advice_that_no_longer_applies_is_closed():
    e = {"t1": {"id": 5, "kind": "practice", "status": "active", "evidence": 4},
         "t2": {"id": 6, "kind": "practice", "status": "dismissed", "evidence": 4}}
    assert sorted(la.plan_sync(e, [])["retire"]) == [(5, "done"), (6, "superseded")]


def test_dismissed_advice_stays_hidden_until_something_changes():
    e = {"t1": {"id": 5, "kind": "review_lesson", "status": "dismissed", "evidence": 4}}
    assert la.plan_sync(e, [rec(evidence=4)]) == {"retire": [], "update": [], "insert": []}
    plan = la.plan_sync(e, [rec(evidence=5)])                                  # a new quiz happened
    assert plan["retire"] == [(5, "superseded")] and len(plan["insert"]) == 1


# ======================= the service =======================
def test_only_new_review_or_tutor_recommendations_notify(app, monkeypatch):
    sent = []
    monkeypatch.setattr(rs.notification_service, "notify", lambda *a: sent.append(a))
    inserted = [(7, {"kind": "human_tutor", "title": "Tutor", "message": "m"}),
                (8, {"kind": "next_lesson", "title": "Next", "message": "m"}),
                (9, {"kind": "practice", "title": "Practice", "message": "m"})]
    with app.app_context():
        rs.notify_new(1, inserted)
    assert [a[5] for a in sent] == ["rec:7", "rec:9"] and sent[0][1] == "recommendation"


def test_a_notification_failure_is_swallowed(app, monkeypatch):
    def broken(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(rs.notification_service, "notify", broken)
    with app.app_context():
        rs.notify_new(1, [(7, {"kind": "human_tutor", "title": "T", "message": "m"})])


def test_safe_run_is_skipped_in_tests_and_never_raises_in_real_use(monkeypatch):
    monkeypatch.setattr(rs, "run_agent", lambda uid: pytest.fail("must not run under TESTING"))
    with create_app(P13Config).app_context():
        assert rs.safe_run(1) == []

    def broken(uid):
        raise RuntimeError("db down")
    monkeypatch.setattr(rs, "run_agent", broken)
    with create_app(LiveConfig).app_context():
        assert rs.safe_run(1) == []


def test_run_agent_decides_then_saves_then_notifies(app, monkeypatch):
    calls = []
    monkeypatch.setattr(rs, "compute", lambda uid: calls.append("compute") or ["d"])
    monkeypatch.setattr(rs, "sync", lambda uid, d: calls.append(("sync", d)) or ["ins"])
    monkeypatch.setattr(rs, "notify_new", lambda uid, ins: calls.append(("notify", ins)))
    with app.app_context():
        assert rs.run_agent(1) == ["d"]
    assert calls == ["compute", ("sync", ["d"]), ("notify", ["ins"])]


def test_stored_reasoning_is_parsed_safely():
    assert rs._load(json.dumps({"steps": ["a"]})) == {"steps": ["a"]}
    assert rs._load("not json") == {"steps": []} and rs._load(None) == {"steps": []}
    assert rs._load({"steps": []}) == {"steps": []}


# ======================= routes =======================
REC = {"id": 3, "kind": "review_lesson", "difficulty": None, "title": "<b>Review</b>: Functions",
       "message": "Review this lesson.", "reasoning": {"rule": "R1_review", "steps": ["Quiz results: 90%, 55%."]},
       "topic_id": 2, "subject_id": 4, "lesson_id": 11, "created_at": None}


@pytest.mark.parametrize("path", ["/student/learning/recommendations"])
def test_only_students_can_open_recommendations(client, monkeypatch, path):
    assert client.get(path).status_code == 302
    for role in ("tutor", "admin"):
        login_as(client, monkeypatch, role)
        assert client.get(path).status_code == 403
        assert client.post("/student/learning/recommendations/3/dismiss").status_code == 403


def test_the_page_refreshes_the_agent_and_shows_the_reasoning(client, monkeypatch):
    login_as(client, monkeypatch)
    ran = []
    monkeypatch.setattr(rs, "safe_run", lambda uid: ran.append(uid) or [])
    monkeypatch.setattr(rs, "list_active", lambda uid, limit=50: [dict(REC),
        dict(REC, id=4, kind="practice", title="Practice", difficulty="easy"),
        dict(REC, id=5, kind="human_tutor", title="Tutor")])
    page = client.get("/student/learning/recommendations")
    assert page.status_code == 200 and ran == [1]
    assert b"Why this recommendation?" in page.data and b"90%, 55%." in page.data
    assert b"<b>Review</b>" not in page.data and b"&lt;b&gt;Review" in page.data
    assert b"/student/learning/lessons/11" in page.data and b"Find a student tutor" in page.data
    assert b"difficulty=easy" in page.data and b"not diagnoses" in page.data


def test_empty_state_and_database_error(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(rs, "safe_run", lambda uid: [])
    monkeypatch.setattr(rs, "list_active", lambda uid, limit=50: [])
    assert b"No recommendations right now" in client.get("/student/learning/recommendations").data

    def broken(uid, limit=50):
        raise RuntimeError("db down")
    monkeypatch.setattr(rs, "list_active", broken)
    assert b"Could not load your recommendations" in client.get("/student/learning/recommendations").data


def test_dismissing_uses_the_logged_in_student(client, monkeypatch):
    login_as(client, monkeypatch)
    seen = {}
    monkeypatch.setattr(rs, "dismiss", lambda rid, uid: seen.update(r=rid, u=uid) or True)
    assert client.post("/student/learning/recommendations/3/dismiss").status_code == 302
    assert seen == {"r": 3, "u": 1}
    monkeypatch.setattr(rs, "dismiss", lambda rid, uid: False)
    page = client.post("/student/learning/recommendations/9/dismiss", follow_redirects=True)
    assert b"not found" in page.data


def test_completing_a_lesson_triggers_the_agent(client, monkeypatch):
    login_as(client, monkeypatch)
    ran = []
    monkeypatch.setattr(learning_service, "get_lesson", lambda lid, uid: {"id": 10, "subject_id": 4})
    monkeypatch.setattr(learning_service, "mark_complete", lambda uid, lid: True)
    monkeypatch.setattr(rs, "safe_run", lambda uid: ran.append(uid))
    assert client.post("/student/learning/lessons/10/complete").status_code == 302 and ran == [1]
    monkeypatch.setattr(learning_service, "mark_complete", lambda uid, lid: False)   # already done
    client.post("/student/learning/lessons/10/complete")
    assert ran == [1]                                                                # not run again


def test_submitting_a_quiz_triggers_the_agent(client, monkeypatch):
    login_as(client, monkeypatch)
    ran = []
    monkeypatch.setattr(quiz_service, "get_quiz", lambda qid, uid: {"id": 1, "mode": "practice"})
    monkeypatch.setattr(quiz_service, "save_attempt", lambda quiz, uid, form: 33)
    monkeypatch.setattr(rs, "safe_run", lambda uid: ran.append(uid))
    response = client.post("/student/quizzes/1/submit", data={})
    assert response.status_code == 302 and response.headers["Location"].endswith("/attempts/33")
    assert ran == [1]


def test_a_recommendation_can_prefill_the_quiz_form(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(subject_service, "list_subjects", lambda active_only=True: [
        {"id": 4, "name": "Python Programming", "category": "Computing", "is_active": 1}])
    monkeypatch.setattr(quiz_service, "list_quizzes", lambda uid: [])
    monkeypatch.setattr(learning_service, "list_topics", lambda: [
        {"id": 7, "subject_id": 4, "name": "Functions", "level": 3, "subject_name": "Python Programming"}])
    page = client.get("/student/quizzes/?subject_id=4&topic_id=7&difficulty=hard")
    assert b'value="4" selected' in page.data and b'value="7" selected' in page.data
    assert b'value="hard" selected' in page.data
    junk = client.get("/student/quizzes/?subject_id=abc&topic_id=-1&difficulty=impossible")
    assert junk.status_code == 200 and b'value="medium" selected' in junk.data