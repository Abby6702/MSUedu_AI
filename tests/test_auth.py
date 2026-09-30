"""Run with:  python -m pytest -v
These tests do NOT need MySQL: the database lookup is replaced by a fake."""
import pytest
from werkzeug.security import check_password_hash, generate_password_hash
from config import Config
from app import create_app, validators
from app.services import user_service


class AuthTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False   # forms are tested without a token here


@pytest.fixture
def client():
    return create_app(AuthTestConfig).test_client()


def login_as(client, monkeypatch, role):
    """Pretend a user with this role is logged in (fictional data)."""
    fake = {"id": 1, "full_name": "Test Person", "email": "test@example.com",
            "role": role, "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: fake)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


# ---- validation ----
def test_good_registration_passes():
    form = {"full_name": "Juan Dela Cruz", "email": "Juan@Example.com", "role": "student",
            "password": "abc12345", "confirm_password": "abc12345"}
    data, errors = validators.validate_registration(form)
    assert errors == []
    assert data["email"] == "juan@example.com"   # lower-cased


def test_admin_cannot_self_register():
    form = {"full_name": "Evil User", "email": "e@example.com", "role": "admin",
            "password": "abc12345", "confirm_password": "abc12345"}
    _, errors = validators.validate_registration(form)
    assert errors


@pytest.mark.parametrize("password", ["short1", "onlyletters", "12345678"])
def test_weak_passwords_rejected(password):
    assert validators.password_errors(password)


def test_password_mismatch_rejected():
    form = {"full_name": "Ana Reyes", "email": "ana@example.com", "role": "tutor",
            "password": "abc12345", "confirm_password": "different1"}
    _, errors = validators.validate_registration(form)
    assert any("match" in e for e in errors)


def test_password_is_hashed_not_stored_plain():
    hashed = generate_password_hash("abc12345")
    assert hashed != "abc12345"
    assert check_password_hash(hashed, "abc12345")
    assert not check_password_hash(hashed, "wrong-password")


# ---- access control ----
@pytest.mark.parametrize("path", ["/dashboard", "/profile", "/student/dashboard",
                                  "/tutor/dashboard", "/admin/dashboard"])
def test_anonymous_users_are_sent_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_student_cannot_open_admin_or_tutor_pages(client, monkeypatch):
    login_as(client, monkeypatch, "student")
    assert client.get("/admin/dashboard").status_code == 403
    assert client.get("/tutor/dashboard").status_code == 403


def test_tutor_cannot_open_student_or_admin_pages(client, monkeypatch):
    login_as(client, monkeypatch, "tutor")
    assert client.get("/student/dashboard").status_code == 403
    assert client.get("/admin/dashboard").status_code == 403


def test_dashboard_redirects_by_role(client, monkeypatch):
    login_as(client, monkeypatch, "admin")
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/dashboard")


def test_logout_requires_post(client):
    assert client.get("/logout").status_code == 405