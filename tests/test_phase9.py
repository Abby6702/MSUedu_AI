"""Run with:  python -m pytest -v
MySQL is FAKED. These tests prove the permission rules, lockouts, password handling,
session invalidation, security headers and admin actions."""
from datetime import datetime

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app, security
from app import validators, validators_admin as va
from app.services import admin_service, login_guard as lg, settings_service
from app.services import user_service
from config import Config


class P9Config(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


class NoCspConfig(P9Config):
    CSP_ENABLED = False


@pytest.fixture
def app():
    return create_app(P9Config)


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, monkeypatch, role="student", sv=None, **extra):
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1, **extra}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        if sv is not None:
            sess["sv"] = sv


NOW = datetime(2026, 10, 5, 6, 0)


# ======================= security headers and error pages =======================
def test_security_headers_are_present(client):
    headers = client.get("/login").headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "same-origin"
    assert "Strict-Transport-Security" not in headers          # only when HTTPS is switched on


def test_csp_can_be_switched_off_for_debugging():
    assert "Content-Security-Policy" not in create_app(NoCspConfig).test_client().get("/login").headers


def test_friendly_error_pages(client):
    response = client.get("/logout")                            # logout only accepts POST
    assert response.status_code == 405 and b"Method not allowed" in response.data
    assert b"Traceback" not in response.data


def test_oversized_requests_are_refused(client):
    response = client.post("/login", data={"email": "x" * (2 * 1024 * 1024)})
    assert response.status_code == 413 and b"too large" in response.data


# ======================= keyed hashes and temporary passwords =======================
def test_digest_is_stable_case_insensitive_and_not_the_input(app):
    with app.app_context():
        assert security.digest("A@Example.com") == security.digest("a@example.com")
        assert len(security.digest("x")) == 64 and "example" not in security.digest("a@example.com")


def test_temp_passwords_are_valid_and_random():
    seen = {security.generate_temp_password() for _ in range(50)}
    assert len(seen) == 50
    for password in seen:
        assert len(password) == 12 and validators.password_errors(password) == []


# ======================= login lockout =======================
def fake_counts(monkeypatch, first, second):
    answers = iter([{"n": first}, {"n": second}])
    monkeypatch.setattr(lg, "query_one", lambda sql, params=None: next(answers))


@pytest.mark.parametrize("by_identity,by_ip,locked", [(5, 0, True), (0, 20, True),
                                                      (4, 19, False), (0, 0, False)])
def test_lockout_thresholds(app, monkeypatch, by_identity, by_ip, locked):
    fake_counts(monkeypatch, by_identity, by_ip)
    with app.app_context():
        assert lg.is_locked("a@example.com", "1.2.3.4") is locked


def test_lockout_fails_open_if_its_table_breaks(app, monkeypatch):
    def broken(sql, params=None):
        raise RuntimeError("no table")
    monkeypatch.setattr(lg, "query_one", broken)
    with app.app_context():
        assert lg.is_locked("a@example.com", "1.2.3.4") is False


def test_failures_are_stored_as_hashes_only(app, monkeypatch):
    calls = []
    monkeypatch.setattr(lg, "execute", lambda sql, params=None: calls.append((sql, params)))
    with app.app_context():
        lg.record_failure("victim@example.com", "203.0.113.9")
    insert = calls[0][1]
    assert len(insert[0]) == 64 and len(insert[1]) == 64
    assert "victim" not in str(insert) and "203.0.113" not in str(insert)
    assert "DELETE FROM login_attempts" in calls[1][0]           # old rows are cleaned up


# ======================= login route =======================
def good_user(**changes):
    user = {"id": 1, "full_name": "Test Person", "email": "t@example.com",
            "password_hash": generate_password_hash("abc12345"), "role": "student",
            "is_active": 1, "session_version": 3}
    user.update(changes)
    return user


@pytest.fixture
def login_env(monkeypatch):
    env = {"failures": [], "cleared": [], "lookups": [], "user": good_user(), "locked": False}
    monkeypatch.setattr(lg, "is_locked", lambda ident, ip: env["locked"])
    monkeypatch.setattr(lg, "record_failure", lambda ident, ip: env["failures"].append((ident, ip)))
    monkeypatch.setattr(lg, "clear", lambda ident: env["cleared"].append(ident))
    monkeypatch.setattr(user_service, "get_user_for_login",
                        lambda email: env["lookups"].append(email) or env["user"])
    monkeypatch.setattr(user_service, "record_login", lambda uid: None)
    return env


def test_good_login_sets_the_session_version(client, login_env):
    response = client.post("/login", data={"email": "T@Example.com", "password": "abc12345"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert sess["user_id"] == 1 and sess["sv"] == 3
    assert login_env["cleared"] == ["t@example.com"] and login_env["failures"] == []


def test_wrong_password_is_counted_with_a_generic_message(client, login_env):
    response = client.post("/login", data={"email": "t@example.com", "password": "wrong-pass1"})
    assert response.status_code == 200 and b"Incorrect email or password" in response.data
    assert login_env["failures"] == [("t@example.com", "127.0.0.1")]


def test_unknown_and_deactivated_accounts_look_the_same(client, login_env):
    login_env["user"] = None
    unknown = client.post("/login", data={"email": "nobody@example.com", "password": "abc12345"})
    login_env["user"] = good_user(is_active=0)
    inactive = client.post("/login", data={"email": "t@example.com", "password": "abc12345"})
    for response in (unknown, inactive):
        assert b"Incorrect email or password" in response.data
    assert len(login_env["failures"]) == 2


def test_locked_accounts_refuse_even_the_right_password(client, login_env):
    login_env["locked"] = True
    response = client.post("/login", data={"email": "t@example.com", "password": "abc12345"})
    assert b"Too many failed attempts" in response.data
    assert login_env["lookups"] == []                            # the account was not even looked up
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ======================= registration switch =======================
def test_registration_can_be_closed(client, monkeypatch):
    monkeypatch.setattr(settings_service, "registration_open", lambda: False)
    monkeypatch.setattr(user_service, "create_user", lambda *a, **k: pytest.fail("must not create"))
    assert client.get("/register").status_code == 403
    response = client.post("/register", data={"full_name": "New Person", "email": "n@example.com",
                                              "role": "student", "password": "abc12345",
                                              "confirm_password": "abc12345"})
    assert response.status_code == 403 and b"Registration is closed" in response.data


# ======================= sessions: version and forced password change =======================
def test_a_changed_session_version_ends_old_sessions(client, monkeypatch):
    login_as(client, monkeypatch, session_version=1)             # session has no matching "sv"
    response = client.get("/notifications/settings")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_a_matching_session_version_is_accepted(client, monkeypatch):
    from app.services import notification_service as ns
    monkeypatch.setattr(ns, "reminders_enabled", lambda uid: True)
    login_as(client, monkeypatch, sv=1, session_version=1)
    assert client.get("/notifications/settings").status_code == 200


def test_forced_password_change_blocks_everything_else(client, monkeypatch):
    login_as(client, monkeypatch, must_change_password=1)
    response = client.get("/notifications/")
    assert response.status_code == 302 and response.headers["Location"].endswith("/password")
    assert client.get("/student/tutors").status_code == 302
    page = client.get("/password")
    assert page.status_code == 200 and b"must choose a new password" in page.data
    assert client.get("/static/css/style.css").status_code == 200
    assert client.post("/logout").status_code == 302              # logging out is still possible


# ======================= changing your own password =======================
@pytest.fixture
def pw_env(monkeypatch):
    env = {"set": [], "failures": [], "audits": [], "locked": False}
    monkeypatch.setattr(user_service, "get_password_hash",
                        lambda uid: generate_password_hash("oldpass123"))
    monkeypatch.setattr(user_service, "set_password", lambda uid, pw: env["set"].append((uid, pw)) or 5)
    monkeypatch.setattr(user_service, "log_audit", lambda *a, **k: env["audits"].append(a))
    monkeypatch.setattr(lg, "is_locked", lambda ident, ip: env["locked"])
    monkeypatch.setattr(lg, "record_failure", lambda ident, ip: env["failures"].append(ident))
    monkeypatch.setattr(lg, "clear", lambda ident: None)
    return env


def post_pw(client, current="oldpass123", new="newpass456", confirm="newpass456"):
    return client.post("/password", data={"current_password": current, "new_password": new,
                                          "confirm_password": confirm})


def test_password_change_works_and_keeps_this_session(client, monkeypatch, pw_env):
    login_as(client, monkeypatch)
    response = post_pw(client)
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")
    assert pw_env["set"] == [(1, "newpass456")]
    with client.session_transaction() as sess:
        assert sess["sv"] == 5                                   # this session survives the bump
    assert pw_env["audits"][0][1] == "password_changed"
    assert "newpass456" not in str(pw_env["audits"])


def test_wrong_current_password_is_counted_and_refused(client, monkeypatch, pw_env):
    login_as(client, monkeypatch)
    response = post_pw(client, current="not-my-password1")
    assert b"current password is incorrect" in response.data
    assert pw_env["set"] == [] and pw_env["failures"] == ["pwchange:1"]


@pytest.mark.parametrize("new,confirm,fragment", [
    ("short1", "short1", b"at least 8"),
    ("onlyletters", "onlyletters", b"one letter and one number"),
    ("newpass456", "different789", b"do not match"),
    ("oldpass123", "oldpass123", b"different from the current"),
])
def test_bad_new_passwords_are_refused(client, monkeypatch, pw_env, new, confirm, fragment):
    login_as(client, monkeypatch)
    response = post_pw(client, new=new, confirm=confirm)
    assert response.status_code == 200 and fragment in response.data and pw_env["set"] == []


def test_locked_password_form_changes_nothing(client, monkeypatch, pw_env):
    login_as(client, monkeypatch)
    pw_env["locked"] = True
    assert b"Too many failed attempts" in post_pw(client).data and pw_env["set"] == []


# ======================= settings and admin filters =======================
@pytest.fixture(autouse=False)
def fresh_settings():
    settings_service.clear_cache()
    yield
    settings_service.clear_cache()


def test_settings_defaults_cache_and_save(monkeypatch, fresh_settings):
    calls = []
    monkeypatch.setattr(settings_service, "query_all",
                        lambda sql, params=None: calls.append(1) or [
                            {"setting_key": "announcement", "setting_value": "Hello"},
                            {"setting_key": "not_a_real_setting", "setting_value": "x"}])
    values = settings_service.get_all()
    assert values == {"announcement": "Hello", "registration_open": "true"}   # unknown key ignored
    settings_service.get_all()
    assert len(calls) == 1                                                    # second read is cached
    saved = []
    monkeypatch.setattr(settings_service, "execute", lambda sql, params=None: saved.append(params))
    settings_service.save(9, {"registration_open": "false", "evil_key": "x"})
    assert [p[0] for p in saved] == ["registration_open"]                     # only known keys
    settings_service.get_all()
    assert len(calls) == 2                                                    # saving cleared the cache


def test_settings_fall_back_to_defaults_when_the_database_fails(app, monkeypatch, fresh_settings):
    def broken(sql, params=None):
        raise RuntimeError("down")
    monkeypatch.setattr(settings_service, "query_all", broken)
    with app.app_context():
        assert settings_service.registration_open() is True
        assert settings_service.announcement() == ""


def test_admin_filters_are_sanitised():
    f = va.parse_user_filters({"role": "root", "status": "maybe", "q": "  a   b  "})
    assert f == {"q": "a b", "role": "", "status": ""}
    assert va.parse_page({"page": "abc"}) == 1 and va.parse_page({"page": "0"}) == 1
    assert va.parse_page({"page": "3"}) == 3 and va.parse_page({"page": "99999999"}) == 10000
    assert va.parse_request_status({"status": "hacked"}) == ""
    assert va.parse_request_status({"status": "pending"}) == "pending"
    assert va.parse_feedback_filter({"show": "hidden"}) == "hidden"
    assert va.parse_audit_action({"action": "x'; DROP TABLE users;--"}) == ""
    assert va.parse_audit_action({"action": "user_deactivated"}) == "user_deactivated"


def test_settings_validation():
    values, errors = va.validate_settings({"announcement": "  Exams   next week  ", "registration_open": "on"})
    assert errors == [] and values == {"announcement": "Exams next week", "registration_open": "true"}
    assert va.validate_settings({})[0]["registration_open"] == "false"       # unticked = closed
    assert va.validate_settings({"announcement": "x" * 301})[1]


def test_user_search_keeps_typed_text_out_of_sql():
    where, params = admin_service._user_where({"q": "x'; DROP TABLE users; --", "role": "", "status": ""})
    assert "DROP TABLE" not in where and any("DROP TABLE" in str(p) for p in params)
    where, params = admin_service._user_where({"q": "", "role": "tutor", "status": "inactive"})
    assert params == ["tutor", 0]


def test_percent_helper():
    assert admin_service.percent(3, 4) == 75 and admin_service.percent(0, 0) is None


# ======================= admin routes: permissions =======================
ADMIN_GETS = ["/admin/dashboard", "/admin/users", "/admin/requests", "/admin/feedback",
              "/admin/audit", "/admin/reports", "/admin/settings", "/admin/users/5/deactivate"]
ADMIN_POSTS = ["/admin/users/5/deactivate", "/admin/users/5/reset_password",
               "/admin/feedback/3/hide", "/admin/settings"]


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_anonymous_users_are_sent_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("role", ["student", "tutor"])
def test_non_admins_are_blocked_from_every_admin_page(client, monkeypatch, role):
    login_as(client, monkeypatch, role)
    for path in ADMIN_GETS:
        assert client.get(path).status_code == 403
    for path in ADMIN_POSTS:
        assert client.post(path, data={}).status_code == 403


# ======================= admin routes: pages render safely =======================
def test_dashboard_shows_statistics(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(admin_service, "overview", lambda: {
        "users": {"student": 7, "tutor": 3, "admin": 1}, "approved_tutors": 2, "pending_tutors": 1,
        "active_subjects": 8, "requests_total": 12, "requests_open": 4, "sessions_completed": 5,
        "feedback_visible": 3, "inactive_users": 1})
    response = client.get("/admin/dashboard")
    assert response.status_code == 200 and b"Completed sessions" in response.data


def test_dashboard_survives_a_database_error(client, monkeypatch):
    login_as(client, monkeypatch, "admin")

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(admin_service, "overview", broken)
    response = client.get("/admin/dashboard")
    assert response.status_code == 200 and b"Could not load the statistics" in response.data


def test_user_list_escapes_names_and_hides_admin_actions(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    rows = [{"id": 5, "full_name": "<b>Fictional</b>", "email": "f@example.com", "role": "student",
             "is_active": 1, "created_at": NOW, "last_login_at": None, "approval_status": None},
            {"id": 9, "full_name": "Other Admin", "email": "a@example.com", "role": "admin",
             "is_active": 1, "created_at": NOW, "last_login_at": NOW, "approval_status": None}]
    monkeypatch.setattr(admin_service, "list_users", lambda f, page: (rows, 2, 1))
    response = client.get("/admin/users")
    assert response.status_code == 200 and b"&lt;b&gt;Fictional" in response.data
    assert b"<b>Fictional</b>" not in response.data and b"Never" in response.data
    assert b"/admin/users/5/deactivate" in response.data
    assert b"/admin/users/9/" not in response.data                # no actions for administrators


def test_audit_page_escapes_details(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(admin_service, "list_audit", lambda action, page: ([
        {"id": 1, "action": "tutor_approved", "target_type": "user", "target_id": 4,
         "details": "<i>x</i>", "created_at": NOW, "actor_name": "Admin"}], 1, 1))
    monkeypatch.setattr(admin_service, "audit_actions", lambda: ["tutor_approved"])
    response = client.get("/admin/audit?action=tutor_approved")
    assert response.status_code == 200 and b"&lt;i&gt;x" in response.data


def test_feedback_and_request_pages_render(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(admin_service, "list_feedback", lambda show, page: ([
        {"id": 3, "rating": 2, "comment": "<script>alert(1)</script>", "is_hidden": 0,
         "created_at": NOW, "tutor_name": "Fictional Tutor", "subject_name": "Calculus 1"}], 1, 1))
    page = client.get("/admin/feedback")
    assert page.status_code == 200 and b"<script>alert(1)</script>" not in page.data
    monkeypatch.setattr(admin_service, "list_requests", lambda status, page: ([
        {"id": 8, "topic": "Limits", "status": "pending", "session_format": "online",
         "start_at": NOW, "end_at": NOW, "subject_name": "Calculus 1",
         "student_name": "Fictional Student", "tutor_name": "Fictional Tutor"}], 1, 1))
    assert b"Fictional Student" in client.get("/admin/requests?status=pending").data


def test_reports_page_renders(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(admin_service, "reports", lambda: {
        "days": 30, "by_status": [{"status": "pending", "n": 2}],
        "tutors": [{"approval_status": "approved", "n": 1}],
        "per_subject": [{"name": "Calculus 1", "n": 3}], "ratings": {"n": 2, "avg": 4.5},
        "ai": [{"feature": "chat", "total": 4, "ok": 3, "rate": 75}],
        "proposals": [{"status": "prepared", "n": 1}]})
    response = client.get("/admin/reports")
    assert response.status_code == 200 and b"4.5 / 5" in response.data and b"75%" in response.data


# ======================= admin actions =======================
STUDENT = {"id": 5, "full_name": "Fictional Student", "email": "s@example.com",
           "role": "student", "is_active": 1}


@pytest.fixture
def action_env(monkeypatch):
    env = {"active": [], "resets": [], "audits": [], "target": dict(STUDENT), "hidden": []}
    monkeypatch.setattr(admin_service, "get_manageable_user", lambda uid: env["target"])
    monkeypatch.setattr(admin_service, "set_active", lambda uid, a: env["active"].append((uid, a)) or True)
    monkeypatch.setattr(admin_service, "reset_password", lambda uid, h: env["resets"].append((uid, h)) or True)
    monkeypatch.setattr(admin_service, "set_feedback_hidden", lambda fid, h: env["hidden"].append((fid, h)) or True)
    monkeypatch.setattr(user_service, "log_audit", lambda *a, **k: env["audits"].append(a))
    return env


def test_administrator_accounts_cannot_be_managed_here(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    action_env["target"] = None                                   # get_manageable_user hides admins
    assert client.get("/admin/users/9/deactivate").status_code == 404
    assert client.post("/admin/users/9/reset_password").status_code == 404
    assert action_env["active"] == [] and action_env["resets"] == []


def test_deactivation_asks_first_then_acts_and_audits(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    page = client.get("/admin/users/5/deactivate")
    assert page.status_code == 200 and b"Yes, deactivate" in page.data
    assert action_env["active"] == []                             # opening the page changed nothing
    assert client.post("/admin/users/5/deactivate").status_code == 302
    assert action_env["active"] == [(5, False)]
    assert action_env["audits"][0][1] == "user_deactivated" and action_env["audits"][0][3] == 5


def test_no_action_when_already_in_that_state(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    assert client.post("/admin/users/5/activate").status_code == 302     # already active
    assert action_env["active"] == [] and action_env["audits"] == []


def test_reactivation(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    action_env["target"] = dict(STUDENT, is_active=0)
    assert client.post("/admin/users/5/activate").status_code == 302
    assert action_env["active"] == [(5, True)]


def test_password_reset_shows_the_password_once_and_stores_only_a_hash(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(security, "generate_temp_password", lambda length=12: "Temp2pass9xy")
    response = client.post("/admin/users/5/reset_password")
    assert response.status_code == 200 and b"Temp2pass9xy" in response.data
    assert response.headers["Cache-Control"] == "no-store"
    uid, stored = action_env["resets"][0]
    assert uid == 5 and stored != "Temp2pass9xy" and check_password_hash(stored, "Temp2pass9xy")
    assert action_env["audits"][0][1] == "password_reset_by_admin"
    assert "Temp2pass9xy" not in str(action_env["audits"])        # never written to the audit log


def test_failed_admin_action_reports_an_error_and_changes_nothing(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")

    def broken(uid, a):
        raise RuntimeError("db down")
    monkeypatch.setattr(admin_service, "set_active", broken)
    response = client.post("/admin/users/5/deactivate", follow_redirects=True)
    assert b"Nothing was changed" in response.data and action_env["audits"] == []


def test_feedback_moderation_is_audited(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    assert client.post("/admin/feedback/3/hide").status_code == 302
    assert action_env["hidden"] == [(3, True)] and action_env["audits"][0][1] == "feedback_hidden"
    client.post("/admin/feedback/3/unhide")
    assert action_env["hidden"][-1] == (3, False) and action_env["audits"][-1][1] == "feedback_unhidden"


def test_feedback_moderation_with_no_change_is_reported(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(admin_service, "set_feedback_hidden", lambda fid, h: False)
    response = client.post("/admin/feedback/3/hide", follow_redirects=True)
    assert b"not found or is already" in response.data and action_env["audits"] == []


def test_settings_are_saved_and_audited(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    saved = {}
    monkeypatch.setattr(settings_service, "save", lambda uid, values: saved.update(u=uid, v=values))
    monkeypatch.setattr(settings_service, "get_all", lambda: {"announcement": "", "registration_open": "true"})
    response = client.post("/admin/settings", data={"announcement": "Exams next week"})
    assert response.status_code == 302
    assert saved["u"] == 1 and saved["v"] == {"announcement": "Exams next week", "registration_open": "false"}
    assert action_env["audits"][0][1] == "settings_changed"


def test_bad_settings_are_not_saved(client, monkeypatch, action_env):
    login_as(client, monkeypatch, "admin")
    monkeypatch.setattr(settings_service, "save", lambda *a: pytest.fail("must not save"))
    response = client.post("/admin/settings", data={"announcement": "x" * 301, "registration_open": "on"})
    assert response.status_code == 200 and b"300 characters or fewer" in response.data