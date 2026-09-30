"""Run with:  python -m pytest -v
No MySQL needed: database functions are faked. The real conflict checks that
need MySQL are covered by the manual checklist below."""
from datetime import datetime, timedelta
import pytest
from config import Config
from app import create_app, timeutil, validators_request as vr
from app.services import request_service as rs, tutor_service, user_service


class P4Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def client():
    return create_app(P4Config).test_client()


def login_as(client, monkeypatch, role):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


def future_date(days):
    return (timeutil.to_local(timeutil.utcnow()) + timedelta(days=days)).strftime("%Y-%m-%d")


# ---- time conversion ----
def test_philippine_time_is_converted_to_utc():
    assert timeutil.local_to_utc("2026-10-06", "14:00") == datetime(2026, 10, 6, 6, 0)


def test_bad_date_or_time_returns_none():
    assert timeutil.local_to_utc("not-a-date", "14:00") is None
    assert timeutil.local_to_utc("2026-10-06", "25:00") is None


def test_display_is_in_philippine_time():
    text = timeutil.format_local(datetime(2026, 10, 6, 6, 0))
    assert "2:00 PM" in text and "06 Oct 2026" in text


# ---- form validation ----
def test_valid_when_passes_and_computes_end():
    start, end, duration, errors = vr.validate_when(
        {"date": future_date(3), "time": "10:00", "duration": "60"})
    assert errors == [] and end - start == timedelta(minutes=60) and duration == 60


@pytest.mark.parametrize("form", [
    {"date": "2020-01-01", "time": "10:00", "duration": "60"},        # in the past
    {"date": future_date(200), "time": "10:00", "duration": "60"},    # too far ahead
    {"date": future_date(3), "time": "10:00", "duration": "45"},      # not an allowed length
    {"date": future_date(3), "time": "", "duration": "60"},           # missing time
    {"date": "garbage", "time": "10:00", "duration": "60"},           # bad date
])
def test_bad_when_rejected(form):
    assert vr.validate_when(form)[3]


def test_request_form_rejects_foreign_subject():
    form = {"subject_id": "99", "topic": "Limits", "format": "online",
            "date": future_date(3), "time": "10:00", "duration": "60"}
    _, errors = vr.validate_request_form(form, valid_subject_ids={1, 2})
    assert any("subject" in e.lower() for e in errors)


# ---- status rules ----
@pytest.mark.parametrize("status,action,role,expected", [
    ("pending", "accept", "tutor", "accepted"),
    ("pending", "accept", "student", None),
    ("pending", "decline", "tutor", "declined"),
    ("pending", "cancel", "student", "cancelled"),
    ("pending", "cancel", "tutor", None),
    ("pending", "complete", "tutor", None),
    ("reschedule_proposed", "accept_proposal", "student", "accepted"),
    ("reschedule_proposed", "accept_proposal", "tutor", None),
    ("accepted", "cancel", "student", "cancelled"),
    ("accepted", "cancel", "tutor", "cancelled"),
    ("accepted", "complete", "tutor", "completed"),
    ("accepted", "complete", "student", None),
    ("declined", "accept", "tutor", None),
    ("cancelled", "cancel", "student", None),
    ("completed", "cancel", "tutor", None),
])
def test_status_transitions(status, action, role, expected):
    assert rs.next_status(status, action, role) == expected


def test_complete_only_offered_after_session_ends():
    now = timeutil.utcnow()
    future = {"status": "accepted", "end_at": now + timedelta(hours=2)}
    past = {"status": "accepted", "end_at": now - timedelta(hours=1)}
    assert rs.available_actions(future, "tutor") == ["cancel"]
    assert "complete" in rs.available_actions(past, "tutor")


# ---- conflict query (fake cursor) ----
class FakeCursor:
    def __init__(self):
        self.sql = self.params = None

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchone(self):
        return None


def test_overlap_query_is_parameterised_and_locks():
    cur = FakeCursor()
    s, e = datetime(2026, 10, 6, 6), datetime(2026, 10, 6, 7)
    assert rs._overlapping_accepted(cur, "tutor_id", 5, s, e, 0) is False
    assert cur.params == (5, 0, e, s)          # overlap means: existing.start < e AND existing.end > s
    assert "status = 'accepted'" in cur.sql and "FOR UPDATE" in cur.sql


def test_overlap_query_refuses_unknown_column():
    with pytest.raises(ValueError):
        rs._overlapping_accepted(FakeCursor(), "id; DROP TABLE users", 1,
                                 datetime.now(), datetime.now())


# ---- routes and permissions ----
NOW = timeutil.utcnow()
FAKE_REQ = {"id": 1, "student_id": 2, "tutor_id": 1, "subject_name": "Calculus 1",
            "topic": "Limits", "description": None, "session_format": "online",
            "start_at": NOW + timedelta(days=2), "end_at": NOW + timedelta(days=2, hours=1),
            "status": "pending", "proposed_start_at": None, "proposed_end_at": None,
            "response_note": None, "student_name": "Fictional Student",
            "tutor_name": "Fictional Tutor"}


@pytest.mark.parametrize("path", ["/student/requests", "/tutor/requests", "/requests/1/cancel",
                                  "/tutor/requests/1/propose", "/student/tutors/1/request"])
def test_anonymous_users_are_sent_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_roles_are_separated(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    assert client.get("/tutor/requests").status_code == 403
    assert client.get("/tutor/requests/1/propose").status_code == 403
    login_as(client, monkeypatch, "tutor")
    assert client.get("/student/requests").status_code == 403
    assert client.get("/student/tutors/1/request").status_code == 403


def test_admin_cannot_act_on_requests(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    assert client.get("/requests/1/accept").status_code == 403


def test_unknown_action_is_404(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    assert client.get("/requests/1/hack").status_code == 404


def test_request_form_for_hidden_tutor_is_404(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    monkeypatch.setattr(tutor_service, "get_public_tutor", lambda _id: None)
    assert client.get("/student/tutors/5/request").status_code == 404


def test_confirm_page_shown_before_accepting(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(rs, "get_for_user", lambda rid, uid: dict(FAKE_REQ))
    response = client.get("/requests/1/accept")
    assert response.status_code == 200 and b"Yes, accept" in response.data


def test_student_cannot_accept_a_request(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    monkeypatch.setattr(rs, "get_for_user", lambda rid, uid: dict(FAKE_REQ))
    response = client.get("/requests/1/accept")
    assert response.status_code == 302 and "/student/requests" in response.headers["Location"]


def test_post_runs_the_action_then_redirects(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    monkeypatch.setattr(rs, "get_for_user", lambda rid, uid: dict(FAKE_REQ))
    monkeypatch.setattr(rs, "perform_action", lambda *a, **k: (True, "Session confirmed."))
    response = client.post("/requests/1/accept")
    assert response.status_code == 302