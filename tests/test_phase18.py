"""Run with:  python -m pytest -v   (Ollama, an online AI service and MySQL are all faked.)"""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from app import create_app
from app import validators_tutor_ai as vta
from app.ai import ollama_client as oc, tutor_logic as tl, tutor_prompts as tp
from app.services import ai_service, notification_service as ns, profile_service as pf
from app.services import request_service, summary_service as ss, tutor_ai_service as tas, user_service
from app.timeutil import utcnow
from config import Config

ROOT = Path(__file__).resolve().parent.parent


class P18Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False
    OLLAMA_MODEL = "test-model"


@pytest.fixture
def app():
    return create_app(P18Config)


@pytest.fixture
def client(app):
    return app.test_client()


USERS = {1: {"id": 1, "full_name": "Sample Student", "email": "s@example.com", "role": "student", "is_active": 1},
         2: {"id": 2, "full_name": "Sample Tutor", "email": "t@example.com", "role": "tutor", "is_active": 1},
         4: {"id": 4, "full_name": "An Admin", "email": "a@example.com", "role": "admin", "is_active": 1},
         5: {"id": 5, "full_name": "Other Tutor", "email": "o@example.com", "role": "tutor", "is_active": 1}}


def T(**kw):
    return utcnow() + timedelta(**kw)


def login_as(client, monkeypatch, user_id):
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: USERS[user_id])
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def sess(**changes):
    base = {"id": 7, "student_id": 1, "tutor_id": 2, "subject_id": 4, "topic": "Loops", "status": "accepted",
            "start_at": T(minutes=-5), "end_at": T(minutes=55), "subject_name": "Python Programming",
            "student_name": "Sample Student", "tutor_name": "Sample Tutor"}
    base.update(changes)
    return base


LESSONS = [{"id": 10, "title": "Loops: for and while", "topic_name": "Loops"},
           {"id": 11, "title": "Functions", "topic_name": "Functions"}]


def quiz_payload():
    return json.dumps({"questions": [
        {"type": "mcq", "question": "What is 2 + 2?", "options": ["3", "4", "5", "6"],
         "answer_index": 1, "explanation": "Two plus two equals four."},
        {"type": "tf", "question": "The derivative of a constant is zero.", "answer": True,
         "explanation": "A constant does not change."},
        {"type": "short", "question": "What is the derivative of x squared?", "answer": "2x",
         "accepted_answers": ["2 x"], "explanation": "Use the power rule."}]})


# ======================= checking the AI's output =======================
def test_lesson_pick_accepts_only_real_lessons():
    allowed = {10, 11}
    ok = tl.parse_lesson_pick('```json\n{"lesson_id": "11", "reason": " Needs   practice. "}\n```', allowed)
    assert ok == {"lesson_id": 11, "reason": "Needs practice."}
    for bad in ('{"lesson_id": 99, "reason": "fine reason"}', '{"lesson_id": true, "reason": "fine reason"}',
                '{"lesson_id": [1], "reason": "fine reason"}', '{"lesson_id": 10, "reason": "no"}',
                '{"reason": "fine reason"}', '["x"]', "not json"):
        with pytest.raises(tl.TutorAiFormatError):
            tl.parse_lesson_pick(bad, allowed)


def test_summary_draft_is_cleaned():
    raw = json.dumps({"topics_covered": " Loops   and ranges ", "strengths": ["Reads code well", "Asks questions"],
                      "improvements": "Off-by-one errors", "practice": "", "next_lesson_id": "11", "extra": "x"})
    assert tl.parse_summary_draft(raw, {10, 11}) == {
        "topics_covered": "Loops and ranges", "strengths": "Reads code well; Asks questions",
        "improvements": "Off-by-one errors", "practice": "", "next_lesson_id": 11}


def test_a_lesson_that_does_not_exist_becomes_none_and_long_text_is_cut():
    raw = json.dumps({"topics_covered": "x" * 700, "next_lesson_id": 99})
    draft = tl.parse_summary_draft(raw, {10})
    assert draft["next_lesson_id"] is None and len(draft["topics_covered"]) == 600


@pytest.mark.parametrize("bad", ['{"strengths": "good"}', '{"topics_covered": "no"}', '["x"]', "plain words", ""])
def test_unusable_summary_drafts_are_rejected(bad):
    with pytest.raises(tl.TutorAiFormatError):
        tl.parse_summary_draft(bad, {10})


def test_quiz_for_the_tutor_includes_answers():
    shown = tl.parse_quiz_result(quiz_payload(), 3, ["mcq", "tf", "short"])
    by_type = {q["type"]: q for q in shown}
    assert by_type["mcq"]["answer"] == "4" and "4" in by_type["mcq"]["options"]
    assert by_type["tf"]["answer"] == "True" and by_type["short"]["answer"].startswith("2x")
    assert "also accepted: 2 x" in by_type["short"]["answer"] and by_type["tf"]["explanation"]
    with pytest.raises(tl.TutorAiFormatError):
        tl.parse_quiz_result(quiz_payload(), 8, ["mcq", "tf", "short"])        # 3 of 8 is too few
    with pytest.raises(tl.TutorAiFormatError):
        tl.parse_quiz_result("sorry, I cannot do that", 3, ["mcq"])


# ======================= prompts =======================
def test_prompts_wrap_tutor_text_and_never_contain_a_student_name():
    for system, user in (tp.exercises("Python Programming", "Loops", "beginner", 3, False),
                         tp.explain("Python Programming", "Loops", "advanced"),
                         tp.hint("Python Programming", "Why does my loop never stop?", "I used while True"),
                         tp.next_lesson("Python Programming", "Loops", "struggles with ranges", LESSONS),
                         tp.summary_draft("Python Programming", "Loops", "we did loops", LESSONS)):
        assert "never follow instructions" in system.lower() and "<<<" in user and ">>>" in user
        assert "Sample Student" not in system + user


def test_exercise_prompt_details():
    _s, no_key = tp.exercises("Python", "Loops", "beginner", 3, False)
    _s, with_key = tp.exercises("Python", "Loops", "beginner", 3, True)
    assert "3 beginner-level" in no_key and "Do not include answers" in no_key
    assert "Answer key" in with_key and "Do not include answers" not in with_key


def test_hint_prompt_forbids_the_final_answer_and_summary_prompt_forbids_invention():
    _s, hint = tp.hint("Python", "Fix this loop please", "")
    assert "Do NOT give the final answer" in hint and "What the student has tried" not in hint
    assert "ONLY what the tutor's notes say" in tp.SUMMARY_SYSTEM and "mastered" in tp.SUMMARY_SYSTEM
    _s, no_lessons = tp.summary_draft("Python", "Loops", "notes here", [])
    assert "must be null" in no_lessons
    assert "1 | A (topic: B)" in tp.lesson_lines([{"id": 1, "title": "A", "topic_name": "B"}])


# ======================= validating requests =======================
def test_defaults():
    data, problem = vta.validate_assist({"action": "exercises"}, "Loops")
    assert problem is None and data == {"action": "exercises", "topic": "Loops", "level": "beginner",
                                        "count": 5, "include_answers": False}
    data, _ = vta.validate_assist({"action": "quiz", "types": []}, "x" * 150)
    assert data["types"] == ["mcq", "tf", "short"] and data["count"] == 5 and len(data["topic"]) == 100
    data, _ = vta.validate_assist({"action": "quiz", "types": ["tf"], "count": "4"}, "Loops")
    assert data["types"] == ["tf"] and data["count"] == 4


@pytest.mark.parametrize("body", [
    None, "x", {}, {"action": "hack"}, {"action": "exercises", "level": "expert"},
    {"action": "exercises", "count": 0}, {"action": "exercises", "count": 9}, {"action": "exercises", "count": True},
    {"action": "exercises", "topic": "x"}, {"action": "exercises", "topic": "y" * 101},
    {"action": "quiz", "count": 2}, {"action": "quiz", "difficulty": "insane"}, {"action": "quiz", "types": ["essay"]},
    {"action": "hint"}, {"action": "hint", "problem": "short"}, {"action": "hint", "problem": "p" * 1501},
    {"action": "hint", "problem": "p" * 20, "attempt": "a" * 1001}, {"action": "next_lesson", "notes": "n" * 1001}])
def test_bad_panel_requests_are_rejected(body):
    assert vta.validate_assist(body, "Loops")[1]


def test_summary_form_validation():
    form = {"topics_covered": "Loops", "strengths": "", "improvements": "Ranges", "practice": "",
            "next_lesson_id": "11", "ai_assisted": "1"}
    data, errors = vta.validate_summary_form(form, {10, 11})
    assert errors == [] and data["next_lesson_id"] == 11 and data["ai_assisted"] is True
    assert vta.validate_summary_form({**form, "ai_assisted": "0"}, {11})[0]["ai_assisted"] is False
    assert vta.validate_summary_form({"topics_covered": "Loops", "ai_assisted": "1"}, set())[0]["next_lesson_id"] is None
    for bad in ({**form, "topics_covered": ""}, {**form, "strengths": "s" * 601}, {**form, "next_lesson_id": "99"},
                {**form, "next_lesson_id": "abc"}):
        assert vta.validate_summary_form(bad, {11})[1]
    assert vta.validate_draft_notes({"notes": "n" * 20})[1] is None
    assert vta.validate_draft_notes({"notes": "short"})[1] and vta.validate_draft_notes("x")[1]


# ======================= the panel endpoint =======================
@pytest.fixture
def env(monkeypatch):
    e = {"sess": sess(), "chat": [], "logs": [], "reply": "Here you go.", "lessons": list(LESSONS),
         "error": None, "limited": False, "saved": [], "notified": [], "existing": None}
    monkeypatch.setattr(ss, "get_session_for_tutor", lambda rid, uid: e["sess"] if rid == 7 and uid == 2 else None)
    monkeypatch.setattr(ss, "lessons_for_subject", lambda sid: e["lessons"])
    monkeypatch.setattr(ss, "get_summary", lambda rid: e["existing"])
    monkeypatch.setattr(ss, "record_topics", lambda rid: "")
    monkeypatch.setattr(ss, "save_summary", lambda rid, tid, data, approve: e["saved"].append((rid, tid, data, approve)))
    monkeypatch.setattr(ai_service, "_rate_limited", lambda uid: e["limited"])
    monkeypatch.setattr(ai_service, "_log_usage", lambda *a, **k: e["logs"].append(a))
    monkeypatch.setattr(ns, "notify", lambda *a: e["notified"].append(a) or True)

    def fake_chat(messages, **kw):
        e["chat"].append((messages, kw))
        if e["error"]:
            raise e["error"]
        return e["reply"]
    monkeypatch.setattr(oc, "chat", fake_chat)
    return e


def ask(client, **body):
    return client.post("/sessions/7/assistant", json=body)


def test_only_the_tutor_of_the_booking_can_use_the_panel(client, monkeypatch, env):
    assert ask(client, action="exercises").status_code == 302                    # not logged in
    for user_id in (1, 4):
        login_as(client, monkeypatch, user_id)
        assert ask(client, action="exercises").status_code == 403                # student, administrator
    login_as(client, monkeypatch, 5)
    assert ask(client, action="exercises").status_code == 404                    # another tutor's booking
    assert env["chat"] == []


@pytest.mark.parametrize("changes", [{"start_at": T(hours=3), "end_at": T(hours=4)},
                                     {"start_at": T(hours=-5), "end_at": T(hours=-4)}, {"status": "completed"}])
def test_the_panel_works_only_while_the_room_is_open(client, monkeypatch, env, changes):
    login_as(client, monkeypatch, 2)
    env["sess"] = sess(**changes)
    response = ask(client, action="exercises")
    assert response.status_code == 403 and b"room is open" in response.data and env["chat"] == []


def test_exercises_use_the_subject_and_topic_but_never_the_student_name(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    response = ask(client, action="exercises", topic="While loops", level="beginner", count=3)
    assert response.status_code == 200 and response.get_json() == {"ok": True, "kind": "text", "text": "Here you go."}
    messages, kwargs = env["chat"][0]
    everything = json.dumps(messages)
    assert "Python Programming" in everything and "While loops" in everything and "3 beginner-level" in everything
    assert "Sample Student" not in everything and kwargs["max_tokens"] == 1500 and "json_mode" not in kwargs
    assert env["logs"][-1][1] == "tutor_assist" and env["logs"][-1][3] is True


def test_a_blank_topic_uses_the_booking_topic(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    ask(client, action="explain", topic="  ", level="advanced")
    assert "Loops" in json.dumps(env["chat"][0][0]) and "advanced" in json.dumps(env["chat"][0][0])


def test_hints_never_ask_for_the_final_answer(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    assert ask(client, action="hint", problem="Why does my loop never stop?", attempt="while True").status_code == 200
    assert "Do NOT give the final answer" in json.dumps(env["chat"][0][0])


def test_the_quiz_is_validated_and_shown_with_answers(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["reply"] = quiz_payload()
    body = ask(client, action="quiz", count=3, difficulty="easy", types=["mcq", "tf", "short"]).get_json()
    assert body["kind"] == "quiz" and len(body["questions"]) == 3
    assert all(q["answer"] and q["explanation"] for q in body["questions"])
    assert env["chat"][0][1]["json_mode"] is True and env["chat"][0][1]["max_tokens"] == 2500
    env["reply"] = "Sorry, I cannot do that."
    response = ask(client, action="quiz", count=3)
    assert response.status_code == 502 and tas.BAD_FORMAT.encode() in response.data
    assert env["logs"][-1][3] is False and env["logs"][-1][4] == "bad_format"


def test_next_lesson_picks_from_the_real_list_only(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["reply"] = '{"lesson_id": 11, "reason": "The student struggled with functions."}'
    body = ask(client, action="next_lesson", notes="confused by functions").get_json()
    assert body["kind"] == "lesson" and body["lesson"] == {"id": 11, "title": "Functions", "topic": "Functions"}
    assert "struggled" in body["reason"] and "11 | Functions" in json.dumps(env["chat"][0][0])
    env["reply"] = '{"lesson_id": 999, "reason": "A lesson that does not exist."}'
    assert ask(client, action="next_lesson").status_code == 502
    env["lessons"] = []
    response = ask(client, action="next_lesson")
    assert response.status_code == 409 and b"no lessons" in response.data


@pytest.mark.parametrize("body", [{}, {"action": "hack"}, {"action": "hint"}, {"action": "quiz", "count": 1},
                                  {"action": "exercises", "count": 99}])
def test_bad_requests_never_reach_the_ai(client, monkeypatch, env, body):
    login_as(client, monkeypatch, 2)
    assert ask(client, **body).status_code == 400
    assert client.post("/sessions/7/assistant", data="not json").status_code == 400
    assert env["chat"] == []


@pytest.mark.parametrize("error,status", [(oc.OllamaUnavailable(), 503), (oc.OllamaNotConfigured(), 503),
                                          (oc.OllamaTimeout(), 504), (oc.OllamaBadResponse(), 502)])
def test_ai_failures_give_friendly_errors(client, monkeypatch, env, error, status):
    login_as(client, monkeypatch, 2)
    env["error"] = error
    response = ask(client, action="exercises")
    assert response.status_code == status and response.get_json()["error"] == ai_service.ERROR_MESSAGES[error.code]
    assert env["logs"][-1][3] is False and env["logs"][-1][4] == error.code


def test_the_rate_limit_applies_to_tutors(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["limited"] = True
    assert ask(client, action="exercises").status_code == 429 and env["chat"] == []


# ======================= the summary page =======================
FORM = {"topics_covered": "Loops and ranges", "strengths": "Asks good questions", "improvements": "Off-by-one errors",
        "practice": "Five range exercises", "next_lesson_id": "11", "ai_assisted": "1", "action": "share"}
PAGE = "/tutor/sessions/7/session-summary"


def test_the_summary_pages_are_for_tutors_only(client, monkeypatch, env):
    for method in ("get", "post"):
        assert getattr(client, method)(PAGE).status_code == 302
    assert client.post(PAGE + "/draft", json={}).status_code == 302
    for user_id in (1, 4):
        login_as(client, monkeypatch, user_id)
        assert client.get(PAGE).status_code == 403 and client.post(PAGE, data=FORM).status_code == 403
        assert client.post(PAGE + "/draft", json={"notes": "n" * 30}).status_code == 403
    login_as(client, monkeypatch, 5)
    assert client.get(PAGE).status_code == 404 and client.post(PAGE, data=FORM).status_code == 404
    assert env["saved"] == []


def test_the_summary_form_loads_with_lessons_and_escapes_text(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["sess"] = sess(topic="<i>Loops</i>")
    page = client.get(PAGE)
    assert page.status_code == 200 and b"Functions (Functions)" in page.data and b"only what you wrote" in page.data
    assert b"<i>Loops</i>" not in page.data and b"&lt;i&gt;Loops" in page.data


@pytest.mark.parametrize("changes", [{"start_at": T(hours=1), "end_at": T(hours=2)}, {"status": "pending"},
                                     {"status": "cancelled"}])
def test_a_summary_needs_a_started_confirmed_session(client, monkeypatch, env, changes):
    login_as(client, monkeypatch, 2)
    env["sess"] = sess(**changes)
    for response in (client.get(PAGE), client.post(PAGE, data=FORM)):
        assert response.status_code == 302 and response.headers["Location"].endswith("/tutor/requests")
    assert client.post(PAGE + "/draft", json={"notes": "n" * 30}).status_code == 403
    assert env["saved"] == []


def test_sharing_saves_and_notifies_the_student_once(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    assert client.post(PAGE, data=FORM).status_code == 302
    request_id, tutor_id, data, approve = env["saved"][0]
    assert (request_id, tutor_id, approve) == (7, 2, True)
    assert data["next_lesson_id"] == 11 and data["ai_assisted"] is True
    note = env["notified"][0]
    assert note[0] == 1 and note[1] == "summary_shared" and note[4] == "/student/sessions/7/session-summary"
    assert note[5] == "summary:7" and "Sample Tutor" in note[3]


def test_a_draft_is_saved_without_telling_the_student(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    assert client.post(PAGE, data={**FORM, "action": "draft"}).status_code == 302
    assert env["saved"][0][3] is False and env["notified"] == []


def test_a_notification_failure_does_not_undo_the_summary(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)

    def broken(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(ns, "notify", broken)
    assert client.post(PAGE, data=FORM).status_code == 302 and len(env["saved"]) == 1


@pytest.mark.parametrize("changes", [{"topics_covered": ""}, {"strengths": "s" * 601}, {"next_lesson_id": "99"},
                                     {"action": "publish"}])
def test_bad_summaries_are_not_saved(client, monkeypatch, env, changes):
    login_as(client, monkeypatch, 2)
    page = client.post(PAGE, data={**FORM, **changes})
    assert page.status_code == 200 and env["saved"] == [] and env["notified"] == []


def test_a_save_failure_is_reported(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)

    def broken(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(ss, "save_summary", broken)
    page = client.post(PAGE, data=FORM)
    assert page.status_code == 200 and b"Could not save the summary" in page.data and env["notified"] == []


def test_an_existing_summary_is_shown_for_editing(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["existing"] = {"topics_covered": "Earlier topics", "strengths": None, "improvements": "Ranges",
                       "practice": None, "next_lesson_id": 11, "status": "approved", "ai_assisted": 1}
    page = client.get(PAGE)
    assert b"Earlier topics" in page.data and b"shared with the student" in page.data
    assert b'value="11" selected' in page.data


# ======================= the AI summary draft =======================
def test_the_draft_uses_only_the_notes_and_the_lesson_list(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    env["reply"] = json.dumps({"topics_covered": "Loops", "strengths": "", "improvements": "Ranges",
                               "practice": "", "next_lesson_id": 11})
    response = client.post(PAGE + "/draft", json={"notes": "We covered loops; ranges were hard."})
    assert response.status_code == 200
    draft = response.get_json()["draft"]
    assert draft["next_lesson_id"] == 11 and draft["improvements"] == "Ranges"
    everything = json.dumps(env["chat"][0][0])
    assert "ranges were hard" in everything and "11 | Functions" in everything and "Sample Student" not in everything
    assert env["logs"][-1][1] == "session_summary" and env["saved"] == []        # a draft is never saved by itself


def test_the_draft_handles_bad_input_and_bad_output(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)
    assert client.post(PAGE + "/draft", json={"notes": "short"}).status_code == 400
    assert client.post(PAGE + "/draft", data="not json").status_code == 400
    assert env["chat"] == []
    env["reply"] = "I cannot summarise that."
    response = client.post(PAGE + "/draft", json={"notes": "n" * 30})
    assert response.status_code == 502 and tas.BAD_FORMAT.encode() in response.data


def test_a_lesson_lookup_failure_is_reported(client, monkeypatch, env):
    login_as(client, monkeypatch, 2)

    def broken(sid):
        raise RuntimeError("db down")
    monkeypatch.setattr(ss, "lessons_for_subject", broken)
    response = client.post(PAGE + "/draft", json={"notes": "n" * 30})
    assert response.status_code == 500 and b"Could not load the lessons" in response.data and env["chat"] == []


# ======================= the student's view =======================
SUMMARY = {"request_id": 7, "topics_covered": "<b>Loops</b>", "strengths": "Curious", "improvements": "Ranges",
           "practice": "Five exercises", "ai_assisted": 1, "approved_at": T(minutes=-1), "start_at": T(minutes=-60),
           "end_at": T(minutes=-1), "subject_name": "Python Programming", "tutor_name": "Sample Tutor",
           "lesson_id": 11, "lesson_title": "Functions"}


def test_students_see_only_shared_summaries_of_their_own_sessions(client, monkeypatch):
    url = "/student/sessions/7/session-summary"
    assert client.get(url).status_code == 302
    for user_id in (2, 4):
        login_as(client, monkeypatch, user_id)
        assert client.get(url).status_code == 403
    login_as(client, monkeypatch, 1)
    seen = {}
    monkeypatch.setattr(ss, "get_approved_for_student", lambda rid, uid: seen.update(r=rid, u=uid))
    assert client.get(url).status_code == 404 and seen == {"r": 7, "u": 1}       # not shared, or not theirs


def test_the_student_page_is_honest_and_safe(client, monkeypatch):
    login_as(client, monkeypatch, 1)
    monkeypatch.setattr(ss, "get_approved_for_student", lambda rid, uid: dict(SUMMARY))
    page = client.get("/student/sessions/7/session-summary")
    assert page.status_code == 200 and b"does not prove" in page.data and b"AI assistance" in page.data
    assert b"/student/learning/lessons/11" in page.data and b"Five exercises" in page.data
    assert b"<b>Loops</b>" not in page.data and b"&lt;b&gt;Loops" in page.data
    monkeypatch.setattr(ss, "get_approved_for_student", lambda rid, uid: dict(SUMMARY, ai_assisted=0, lesson_id=None))
    plain = client.get("/student/sessions/7/session-summary")
    assert b"AI assistance" not in plain.data and b"Suggested next lesson" not in plain.data


# ======================= the profile =======================
PROFILE = {"lessons_done": 1, "lessons_total": 8, "progress_percent": 13, "streak": 1, "study_minutes": 5,
           "quiz_attempts": 0, "quiz_average": None, "sessions_completed": 1, "ai_questions": 0,
           "strong": [], "developing": [], "weak": [], "topics": []}


def test_the_profile_shows_shared_summaries(client, monkeypatch):
    login_as(client, monkeypatch, 1)
    summaries = [{"request_id": 7, "improvements": "<i>Ranges</i>", "approved_at": T(minutes=-1),
                  "subject_name": "Python Programming", "tutor_name": "Sample Tutor",
                  "lesson_id": 11, "lesson_title": "Functions"}]
    monkeypatch.setattr(pf, "build_profile", lambda uid: dict(PROFILE, tutor_summaries=summaries))
    page = client.get("/student/learning/profile")
    assert b"From your tutors" in page.data and b"/student/sessions/7/session-summary" in page.data
    assert b"<i>Ranges</i>" not in page.data and b"&lt;i&gt;Ranges" in page.data
    monkeypatch.setattr(pf, "build_profile", lambda uid: dict(PROFILE, tutor_summaries=[]))
    assert b"From your tutors" not in client.get("/student/learning/profile").data


def test_a_summary_lookup_failure_does_not_break_the_profile(app, monkeypatch):
    def broken(uid, limit=5):
        raise RuntimeError("db down")
    monkeypatch.setattr(ss, "student_summaries", broken)
    with app.app_context():
        assert pf._tutor_summaries(1) == []


# ======================= the live room =======================
def room_booking():
    return {"id": 7, "student_id": 1, "tutor_id": 2, "status": "accepted", "topic": "Loops",
            "subject_name": "Python Programming", "student_name": "Sample Student",
            "tutor_name": "Sample Tutor", "start_at": T(minutes=-5), "end_at": T(minutes=55)}


def test_only_the_tutor_sees_the_ai_panel(client, monkeypatch):
    monkeypatch.setattr(request_service, "get_for_user", lambda rid, uid: room_booking())
    login_as(client, monkeypatch, 2)
    tutor_page = client.get("/sessions/7")
    for expected in (b'id="aiPanel"', b"js/tutor_assistant.js", b"/tutor/sessions/7/session-summary", b"AI-written"):
        assert expected in tutor_page.data
    assert b"Phase 18" not in tutor_page.data
    login_as(client, monkeypatch, 1)
    student_page = client.get("/sessions/7")
    assert b"aiPanel" not in student_page.data and b"tutor_assistant.js" not in student_page.data


# ======================= routes, hygiene and wording =======================
def test_no_two_routes_share_a_path_and_method(app):
    seen = {}
    for rule in app.url_map.iter_rules():
        for method in rule.methods & {"GET", "POST"}:
            key = (rule.rule, method)
            assert key not in seen, f"{method} {rule.rule} is used by {seen[key]} and {rule.endpoint}"
            seen[key] = rule.endpoint


@pytest.mark.parametrize("script", ["tutor_assistant.js", "summary_draft.js"])
def test_the_scripts_never_use_innerhtml(script):
    source = (ROOT / "app" / "static" / "js" / script).read_text(encoding="utf-8")
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval("):
        assert banned not in source


def test_the_pure_files_stay_pure_and_never_use_the_student_name():
    for path in ("ai/tutor_logic.py", "ai/tutor_prompts.py"):
        source = (ROOT / "app" / path).read_text(encoding="utf-8")
        for word in ("flask", "app.db", "requests"):
            assert word not in source
        assert "student_name" not in source
    assert "student_name" not in (ROOT / "app" / "services" / "tutor_ai_service.py").read_text(encoding="utf-8")


def test_summary_queries_always_include_the_owner():
    source = (ROOT / "app" / "services" / "summary_service.py").read_text(encoding="utf-8")
    assert "r.tutor_id = %s" in source and "r.student_id = %s" in source
    assert source.count("ss.status = 'approved'") == 2                              # drafts are never shown to students


def test_the_about_page_describes_the_tutor_ai_helper(client):
    page = client.get("/about")
    assert b"AI helper during sessions" in page.data and b"after your tutor reviews it" in page.data