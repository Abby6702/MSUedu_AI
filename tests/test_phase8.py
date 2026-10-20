"""Run with:  python -m pytest -v
MySQL and Ollama are FAKED. These tests prove who is notified, that duplicates are
blocked, that reminders behave, and who may see feedback and records."""
from datetime import datetime, timedelta

import pytest

from app import create_app, timeutil
from app import validators_progress as vp
from app.ai import ollama_client as oc
from app.services import ai_service
from app.services import mail_service, notification_service as ns
from app.services import progress_service as ps
from app.services import quiz_service, tutor_service, user_service
from app.services import request_service as rs
from config import Config


class P8Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False
    OLLAMA_MODEL = "test-model"


@pytest.fixture
def app():
    return create_app(P8Config)


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role="student"):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


NOW = datetime(2026, 10, 5, 0, 0)


# ======================= reminder rules =======================
def test_parse_hours():
    assert ns.parse_hours("24,1") == [1, 24]
    assert ns.parse_hours(" 2 , x, 0, 500, 12") == [2, 12]
    assert ns.parse_hours("") == [1, 24] and ns.parse_hours("junk") == [1, 24]
    assert len(ns.parse_hours("1,2,3,4,5,6")) == 4


def test_pick_threshold_uses_the_tightest_window():
    hours = [1, 24]
    assert ns.pick_threshold(NOW + timedelta(hours=5), NOW, hours) == 24
    assert ns.pick_threshold(NOW + timedelta(minutes=30), NOW, hours) == 1
    assert ns.pick_threshold(NOW + timedelta(hours=30), NOW, hours) is None
    assert ns.pick_threshold(NOW - timedelta(minutes=1), NOW, hours) is None   # already started


def _session(sid=7, hours_ahead=5):
    return {"id": sid, "student_id": 2, "tutor_id": 3, "topic": "Limits",
            "start_at": NOW + timedelta(hours=hours_ahead),
            "end_at": NOW + timedelta(hours=hours_ahead + 1),
            "proposed_start_at": None, "proposed_end_at": None, "response_note": None,
            "subject_name": "Calculus 1", "student_name": "Fictional Student",
            "tutor_name": "Fictional Tutor"}


@pytest.fixture
def reminder_env(monkeypatch):
    env = {"sessions": [_session()], "muted": [], "saved": []}

    def fake_query_all(sql, params=None):
        if "notification_preferences" in sql:
            return [{"user_id": u} for u in env["muted"]]
        return env["sessions"]
    monkeypatch.setattr(ns, "query_all", fake_query_all)
    monkeypatch.setattr(ns, "notify", lambda *a: env["saved"].append(a) or True)
    return env


def test_reminders_go_to_both_people_once_each(reminder_env):
    assert ns.send_due_reminders([1, 24], now=NOW) == 2
    recipients = {a[0] for a in reminder_env["saved"]}
    assert recipients == {2, 3}
    keys = {a[5] for a in reminder_env["saved"]}
    assert keys == {"remind:7:24:10050500"}                 # includes the start time


def test_muted_users_get_no_reminder(reminder_env):
    reminder_env["muted"] = [2]
    assert ns.send_due_reminders([1, 24], now=NOW) == 1
    assert {a[0] for a in reminder_env["saved"]} == {3}


def test_sessions_outside_every_window_get_nothing(reminder_env):
    reminder_env["sessions"] = [_session(hours_ahead=50)]
    assert ns.send_due_reminders([1, 24], now=NOW) == 0


def test_the_same_reminder_is_not_counted_twice(reminder_env, monkeypatch):
    seen = set()

    def dedupe(user_id, kind, title, body, link, key):
        if (user_id, key) in seen:
            return False
        seen.add((user_id, key))
        return True
    monkeypatch.setattr(ns, "notify", dedupe)
    assert ns.send_due_reminders([1, 24], now=NOW) == 2
    assert ns.send_due_reminders([1, 24], now=NOW) == 0     # second run: nothing new


# ======================= saving a notification =======================
class FakeCur:
    def __init__(self, results):
        self.results, self.sql, self.params = list(results), None, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params
        return self.results.pop(0)


class FakeConn:
    def __init__(self, cur):
        self.cur, self.committed = cur, False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_notify_uses_insert_ignore_and_reports_duplicates(monkeypatch):
    cur = FakeCur([1, 0])
    monkeypatch.setattr(ns, "get_connection", lambda: FakeConn(cur))
    assert ns.notify(2, "reminder", "T" * 300, "B" * 900, "/x", "key1") is True
    assert "INSERT IGNORE" in cur.sql
    assert len(cur.params[2]) == 150 and len(cur.params[3]) == 500      # long text is cut
    assert ns.notify(2, "reminder", "t", "b", "/x", "key1") is False    # duplicate


# ======================= who is told about what =======================
@pytest.mark.parametrize("event,actor,recipient,kind", [
    ("created", 2, 3, "request_new"),
    ("accepted", 3, 2, "request_accepted"),
    ("declined", 3, 2, "request_declined"),
    ("proposal_accepted", 2, 3, "proposal_accepted"),
    ("completed", 3, 2, "session_completed"),
])
def test_each_event_goes_to_the_right_person(event, actor, recipient, kind):
    got = ns.build_request_notification(_session(), event, actor)
    assert got[0] == recipient and got[1] == kind


def test_proposed_time_goes_to_the_student_with_the_new_time():
    row = _session()
    row["proposed_start_at"], row["proposed_end_at"] = NOW + timedelta(days=1), NOW + timedelta(days=1, hours=1)
    got = ns.build_request_notification(row, "proposed", 3)
    assert got[0] == 2 and "suggested" in got[3]


def test_cancel_notifies_the_other_person():
    assert ns.build_request_notification(_session(), "cancelled", 2)[0] == 3     # student cancelled
    assert ns.build_request_notification(_session(), "cancelled", 3)[0] == 2     # tutor cancelled


def test_declined_note_is_included_and_unknown_events_ignored():
    row = _session()
    row["response_note"] = "Busy this week"
    assert "Busy this week" in ns.build_request_notification(row, "declined", 3)[3]
    assert ns.build_request_notification(row, "banana", 3) is None


def test_request_event_emails_only_a_new_booking_notification(monkeypatch):
    row = _session()
    row.update(student_email="student@example.test", tutor_email="tutor@example.test")
    sent = []
    monkeypatch.setattr(ns, "query_one", lambda *args: row)
    monkeypatch.setattr(ns, "notify", lambda *args: True)
    monkeypatch.setattr(mail_service, "send_booking_update", lambda *args: sent.append(args))

    assert ns.request_event(7, "accepted", 3) is True
    assert sent[0][0:2] == ("student@example.test", "Fictional Student")
    assert sent[0][2] == "Request accepted"

    monkeypatch.setattr(ns, "notify", lambda *args: False)
    assert ns.request_event(7, "accepted", 3) is False
    assert len(sent) == 1


def test_completed_notification_links_to_the_feedback_page():
    assert ns.build_request_notification(_session(), "completed", 3)[4] == "/student/sessions/7/feedback"


def test_every_action_creates_a_notification_event():
    assert set(rs.EVENT_BY_ACTION) == set(rs.MESSAGES)
    for event in rs.EVENT_BY_ACTION.values():
        assert ns.build_request_notification(_session(), event, 3) is not None


def test_a_notification_failure_never_breaks_a_booking(app, monkeypatch):
    def boom(*a):
        raise RuntimeError("db down")
    monkeypatch.setattr(ns, "request_event", boom)
    with app.app_context():
        rs._notify("created", 1, 2)              # must not raise


# ======================= validation =======================
def test_feedback_validation():
    data, errors = vp.validate_feedback({"rating": "4", "comment": "  Great  "})
    assert errors == [] and data == {"rating": 4, "comment": "Great"}
    for bad in ({"rating": "0"}, {"rating": "6"}, {"rating": "x"}, {}, {"rating": "3", "comment": "y" * 1001}):
        assert vp.validate_feedback(bad)[1]


def test_record_validation():
    ok = {"topics_covered": "Limits", "outcomes": "Solved 5 limit problems", "summary_text": "Recap",
          "ai_assisted": "1"}
    data, errors = vp.validate_record(ok)
    assert errors == [] and data["ai_assisted"] is True
    data, _ = vp.validate_record({**ok, "summary_text": ""})
    assert data["ai_assisted"] is False                    # no recap, so not AI-assisted
    for bad in ({**ok, "topics_covered": ""}, {**ok, "outcomes": "x"},
                {**ok, "next_steps": "z" * 501}, {**ok, "summary_text": "z" * 1501}):
        assert vp.validate_record(bad)[1]


def test_summary_input_validation():
    values, problem = vp.validate_summary_input({"topics": "Limits", "outcomes": "Practised limits"})
    assert problem is None and values["next_steps"] == ""
    assert vp.validate_summary_input("nope")[1]
    assert vp.validate_summary_input({"topics": "", "outcomes": "Practised limits"})[1]


# ======================= routes and permissions =======================
SESSION = {"id": 9, "student_id": 1, "tutor_id": 5, "topic": "Limits",
           "start_at": NOW, "end_at": NOW + timedelta(hours=1), "subject_name": "Calculus 1",
           "student_name": "Fictional Student", "tutor_name": "Fictional Tutor"}


@pytest.mark.parametrize("path", ["/notifications/", "/notifications/settings", "/student/progress",
                                  "/tutor/feedback", "/student/sessions/9/feedback",
                                  "/tutor/sessions/9/record"])
def test_anonymous_users_are_sent_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_roles_are_separated(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    assert client.get("/tutor/feedback").status_code == 403
    assert client.get("/tutor/sessions/9/record").status_code == 403
    assert client.post("/tutor/sessions/9/summary", json={}).status_code == 403
    login_as(client, monkeypatch, "tutor")
    assert client.get("/student/progress").status_code == 403
    assert client.get("/student/sessions/9/feedback").status_code == 403
    login_as(client, monkeypatch, "admin")
    assert client.get("/student/progress").status_code == 403
    assert client.get("/tutor/feedback").status_code == 403


def test_notification_list_and_badge_link(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ns, "list_for_user", lambda uid, limit=50: [
        {"id": 4, "kind": "request_new", "title": "New tutoring request", "body": "<b>hi</b>",
         "link": "/tutor/requests", "is_read": 0, "created_at": datetime(2026, 10, 5, 6, 0)}])
    response = client.get("/notifications/")
    assert response.status_code == 200 and b"New tutoring request" in response.data
    assert b"<b>hi</b>" not in response.data and b"&lt;b&gt;" in response.data     # escaped


def test_opening_a_notification_marks_it_read_and_redirects_internally(client, monkeypatch):
    login_as(client, monkeypatch)
    marked = {}
    monkeypatch.setattr(ns, "get_own", lambda nid, uid: {"id": nid, "link": "/student/requests", "is_read": 0})
    monkeypatch.setattr(ns, "mark_read", lambda nid, uid: marked.update(n=nid, u=uid))
    response = client.get("/notifications/4/open")
    assert response.status_code == 302 and response.headers["Location"].endswith("/student/requests")
    assert marked == {"n": 4, "u": 1}


@pytest.mark.parametrize("bad_link", ["https://evil.example", "//evil.example", None, "javascript:alert(1)"])
def test_notifications_can_never_redirect_off_site(client, monkeypatch, bad_link):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ns, "get_own", lambda nid, uid: {"id": nid, "link": bad_link, "is_read": 0})
    monkeypatch.setattr(ns, "mark_read", lambda nid, uid: None)
    response = client.get("/notifications/4/open")
    assert response.headers["Location"].endswith("/notifications/")


def test_someone_elses_notification_goes_nowhere(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ns, "get_own", lambda nid, uid: None)
    monkeypatch.setattr(ns, "mark_read", lambda *a: pytest.fail("must not mark"))
    assert client.get("/notifications/4/open").headers["Location"].endswith("/notifications/")


def test_reminder_setting_is_saved(client, monkeypatch):
    login_as(client, monkeypatch)
    saved = {}
    monkeypatch.setattr(ns, "set_reminders_enabled", lambda uid, enabled: saved.update(u=uid, e=enabled))
    assert client.post("/notifications/settings", data={}).status_code == 302
    assert saved == {"u": 1, "e": False}
    client.post("/notifications/settings", data={"reminders_enabled": "on"})
    assert saved["e"] is True


# ---- feedback ----
def feedback_env(monkeypatch, existing=None):
    monkeypatch.setattr(ps, "get_completed_for_student", lambda rid, uid: dict(SESSION))
    monkeypatch.setattr(ps, "get_feedback", lambda rid: existing)
    monkeypatch.setattr(ps, "get_record", lambda rid: None)
    monkeypatch.setattr(ns, "notify", lambda *a: True)


def test_feedback_page_for_someone_elses_or_unfinished_session_is_404(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ps, "get_completed_for_student", lambda rid, uid: None)
    assert client.get("/student/sessions/9/feedback").status_code == 404
    assert client.post("/student/sessions/9/feedback", data={"rating": "5"}).status_code == 404


def test_feedback_is_saved_with_the_right_people(client, monkeypatch):
    login_as(client, monkeypatch)
    feedback_env(monkeypatch)
    saved = {}
    monkeypatch.setattr(ps, "create_feedback", lambda *a: saved.update(args=a))
    response = client.post("/student/sessions/9/feedback", data={"rating": "4", "comment": "Helpful"})
    assert response.status_code == 302
    assert saved["args"] == (9, 1, 5, 4, "Helpful")        # request, student (from login), tutor, rating, comment


def test_bad_feedback_is_not_saved(client, monkeypatch):
    login_as(client, monkeypatch)
    feedback_env(monkeypatch)
    monkeypatch.setattr(ps, "create_feedback", lambda *a: pytest.fail("must not save"))
    response = client.post("/student/sessions/9/feedback", data={"rating": "9"})
    assert response.status_code == 200 and b"Choose a rating" in response.data


def test_feedback_cannot_be_sent_twice(client, monkeypatch):
    login_as(client, monkeypatch)
    feedback_env(monkeypatch, existing={"rating": 5, "comment": "Great", "created_at": NOW})
    monkeypatch.setattr(ps, "create_feedback", lambda *a: pytest.fail("must not save again"))
    response = client.post("/student/sessions/9/feedback", data={"rating": "1"})
    assert response.status_code == 200 and b"already sent feedback" in response.data


def test_a_race_on_feedback_is_handled(client, monkeypatch):
    login_as(client, monkeypatch)
    feedback_env(monkeypatch)

    def duplicate(*a):
        raise ps.FeedbackExists()
    monkeypatch.setattr(ps, "create_feedback", duplicate)
    assert client.post("/student/sessions/9/feedback", data={"rating": "3"}).status_code == 302


# ---- tutor pages ----
def test_tutor_feedback_page_is_anonymous_and_escaped(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "tutor_feedback", lambda tid, limit=50: [
        {"rating": 5, "comment": "<script>alert(1)</script>", "created_at": NOW,
         "subject_name": "Calculus 1"}])
    monkeypatch.setattr(ps, "rating_summary", lambda tid: {"n": 1, "avg": 5.0})
    response = client.get("/tutor/feedback")
    assert response.status_code == 200 and b"5.0 / 5" in response.data
    assert b"<script>alert(1)</script>" not in response.data


def test_record_page_for_someone_elses_session_is_404(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "get_completed_for_tutor", lambda rid, uid: None)
    assert client.get("/tutor/sessions/9/record").status_code == 404
    assert client.post("/tutor/sessions/9/record", data={}).status_code == 404
    assert client.post("/tutor/sessions/9/summary", json={}).status_code == 404


def test_session_record_is_saved(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "get_completed_for_tutor", lambda rid, uid: dict(SESSION))
    saved = {}
    monkeypatch.setattr(ps, "save_record", lambda rid, uid, data: saved.update(r=rid, u=uid, d=data))
    monkeypatch.setattr(ns, "notify", lambda *a: True)
    response = client.post("/tutor/sessions/9/record", data={
        "topics_covered": "Limits", "outcomes": "Solved practice problems",
        "summary_text": "We covered limits.", "ai_assisted": "1"})
    assert response.status_code == 302
    assert saved["r"] == 9 and saved["u"] == 1 and saved["d"]["ai_assisted"] is True


def test_incomplete_record_is_rejected(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(ps, "get_completed_for_tutor", lambda rid, uid: dict(SESSION))
    monkeypatch.setattr(ps, "save_record", lambda *a: pytest.fail("must not save"))
    assert b"Topics covered must be" in client.post("/tutor/sessions/9/record", data={}).data


# ---- AI recap ----
@pytest.fixture
def ai_ready(monkeypatch):
    monkeypatch.setattr(ps, "get_completed_for_tutor", lambda rid, uid: dict(SESSION))
    monkeypatch.setattr(ai_service, "_rate_limited", lambda uid: False)
    monkeypatch.setattr(ai_service, "_log_usage", lambda *a, **k: None)


def test_ai_recap_uses_only_the_tutors_notes(client, monkeypatch, ai_ready):
    login_as(client, monkeypatch, "tutor")
    sent = {}
    monkeypatch.setattr(oc, "chat", lambda messages, **k: sent.update(m=messages) or "Draft recap")
    response = client.post("/tutor/sessions/9/summary",
                           json={"topics": "Limits", "outcomes": "Practised limit laws"})
    assert response.status_code == 200 and response.get_json()["reply"] == "Draft recap"
    assert "ONLY" in sent["m"][0]["content"] and "Practised limit laws" in sent["m"][1]["content"]


def test_ai_recap_bad_input_never_calls_the_model(client, monkeypatch, ai_ready):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(oc, "chat", lambda *a, **k: pytest.fail("model must not be called"))
    assert client.post("/tutor/sessions/9/summary", json={"topics": "", "outcomes": ""}).status_code == 400
    assert client.post("/tutor/sessions/9/summary", data="not json").status_code == 400


def test_ai_recap_failure_is_friendly(client, monkeypatch, ai_ready):
    login_as(client, monkeypatch, "tutor")

    def down(messages, **k):
        raise oc.OllamaUnavailable()
    monkeypatch.setattr(oc, "chat", down)
    response = client.post("/tutor/sessions/9/summary",
                           json={"topics": "Limits", "outcomes": "Practised limit laws"})
    assert response.status_code == 503
    assert response.get_json()["error"] == ai_service.ERROR_MESSAGES["unavailable"]


# ---- student progress and public profile ----
def test_progress_page_states_it_is_not_proof_of_mastery(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(ps, "student_completed_sessions", lambda sid: [
        {"id": 9, "start_at": NOW, "end_at": NOW + timedelta(hours=1), "subject_name": "Calculus 1",
         "tutor_name": "Fictional Tutor", "topics_covered": "Limits", "outcomes": "Practised",
         "next_steps": None, "summary_text": "We covered limits.", "summary_ai_assisted": 1,
         "rating": None}])
    monkeypatch.setattr(quiz_service, "list_quizzes", lambda uid: [])
    monkeypatch.setattr(ps, "activity_counts", lambda uid: {"chat": 3})
    response = client.get("/student/progress")
    assert response.status_code == 200
    assert b"does not prove" in response.data and b"written with AI assistance" in response.data
    assert b"Questions asked in the AI assistant: 3" in response.data


def test_tutor_profile_shows_rating_and_escapes_comments(client, monkeypatch):
    login_as(client, monkeypatch)
    monkeypatch.setattr(tutor_service, "get_public_tutor", lambda tid: {
        "id": 5, "full_name": "Fictional Tutor", "course": "BSCS", "year_level": 3,
        "bio": "Hi", "tutoring_format": "both", "subjects": [{"name": "Calculus 1", "topics": None}],
        "availability": [{"day_name": "Monday", "label": "2:00 PM to 4:00 PM"}]})
    monkeypatch.setattr(ps, "rating_summary", lambda tid: {"n": 2, "avg": 4.5})
    monkeypatch.setattr(ps, "tutor_feedback", lambda tid, limit=5: [
        {"rating": 5, "comment": "<b>Great</b>", "created_at": NOW, "subject_name": "Calculus 1"}])
    response = client.get("/student/tutors/5")
    assert response.status_code == 200 and b"4.5 / 5" in response.data
    assert b"<b>Great</b>" not in response.data and b"&lt;b&gt;Great" in response.data