"""Run with:  python -m pytest -v
These tests need no MySQL: database calls are faked or never reached."""
from datetime import timedelta
import pytest
from config import Config
from app import create_app
from app import validators_tutor as vt
from app.services import tutor_service as ts, user_service, subject_service


class P3Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def client():
    return create_app(P3Config).test_client()


def login_as(client, monkeypatch, role):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


def T(h, m=0):
    return timedelta(hours=h, minutes=m)


# ---- time and slot validation ----
def test_parse_hhmm():
    assert vt.parse_hhmm("14:30") == T(14, 30)
    for bad in ["", "25:00", "9:5", "abc", "12:60"]:
        assert vt.parse_hhmm(bad) is None


def test_valid_slot_passes():
    data, errors = vt.validate_slot({"day_of_week": "0", "start_time": "14:00", "end_time": "16:00"})
    assert errors == [] and data["day"] == 0


@pytest.mark.parametrize("form", [
    {"day_of_week": "7", "start_time": "14:00", "end_time": "16:00"},    # bad day
    {"day_of_week": "1", "start_time": "16:00", "end_time": "14:00"},    # end before start
    {"day_of_week": "1", "start_time": "14:00", "end_time": "14:10"},    # too short
    {"day_of_week": "1", "start_time": "", "end_time": "14:10"},         # missing
])
def test_bad_slots_rejected(form):
    _, errors = vt.validate_slot(form)
    assert errors


# ---- search safety ----
def test_like_pattern_escapes_wildcards():
    assert ts.like_pattern("50%_off") == "%50\\%\\_off%"


def test_search_query_keeps_user_text_out_of_sql():
    evil = "x'; DROP TABLE users; --"
    filters = vt.parse_search_args({"q": evil, "sort": "name; DROP TABLE users"})
    sql, params = ts.build_search_query(filters)
    assert "DROP TABLE" not in sql
    assert any("DROP TABLE" in str(p) for p in params)     # it travels as data only
    assert "ORDER BY u.full_name ASC" in sql                # bad sort fell back to the default
    assert "approval_status = 'approved'" in sql            # students only ever see approved tutors


def test_search_args_are_sanitised():
    f = vt.parse_search_args({"day": "99", "format": "hologram", "subject_id": "abc"})
    assert f["day"] is None and f["format"] == "" and f["subject_id"] is None


# ---- matching rules ----
TUTOR = {"id": 5, "full_name": "Fictional Tutor", "tutoring_format": "online", "topics": "limits"}
SLOTS = [{"day_of_week": 0, "start_time": T(14), "end_time": T(16)}]


def test_match_with_day_and_time_scores_highest():
    r = ts.score_tutor(TUTOR, SLOTS, {"day": 0, "time": T(15), "format": "online"})
    assert r["score"] == 5 and r["notes"] == []
    assert any("Monday" in x for x in r["reasons"])


def test_match_explains_missing_day():
    r = ts.score_tutor(TUTOR, SLOTS, {"day": 2, "time": None, "format": ""})
    assert r["score"] == 1
    assert any("Wednesday" in n for n in r["notes"])


def test_match_time_outside_slot_is_noted_not_claimed():
    r = ts.score_tutor(TUTOR, SLOTS, {"day": 0, "time": T(18), "format": ""})
    assert r["notes"] and not any("preferred time" in x for x in r["reasons"])


def test_match_excludes_wrong_format():
    assert ts.score_tutor(TUTOR, SLOTS, {"day": None, "time": None, "format": "in_person"}) is None


# ---- access control ----
@pytest.mark.parametrize("path", ["/tutor/subjects", "/tutor/availability", "/student/tutors",
                                  "/student/match", "/student/tutors/1", "/admin/tutors",
                                  "/admin/subjects"])
def test_anonymous_users_are_sent_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_student_blocked_from_tutor_and_admin_tools(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    for path in ["/tutor/subjects", "/tutor/availability", "/admin/tutors", "/admin/subjects"]:
        assert client.get(path).status_code == 403
    assert client.post("/admin/tutors/1/review", data={"decision": "approved"}).status_code == 403
    assert client.post("/admin/subjects", data={"name": "Hack"}).status_code == 403


def test_tutor_blocked_from_student_search_and_admin(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    assert client.get("/student/tutors").status_code == 403
    assert client.get("/student/match").status_code == 403
    assert client.get("/admin/tutors").status_code == 403
    assert client.post("/admin/tutors/1/review", data={"decision": "approved"}).status_code == 403
    assert client.post("/admin/subjects/1/toggle").status_code == 403
    

def test_student_search_page_loads_with_fake_data(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    monkeypatch.setattr(ts, "search_tutors", lambda f: [])
    monkeypatch.setattr(subject_service, "list_subjects", lambda active_only=True: [])
    response = client.get("/student/tutors?q=math")
    assert response.status_code == 200
    assert b"No approved tutors" in response.data