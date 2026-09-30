"""Run with:  python -m pytest -v"""
import pytest
from config import Config
from app import create_app


class ConfigForTests(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"


@pytest.fixture
def client():
    app = create_app(ConfigForTests)
    return app.test_client()


def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"MSUEdu" in response.data


def test_health_returns_json(client):
    # 200 if the database is reachable, 503 if not. Either way it must answer.
    response = client.get("/health")
    assert response.status_code in (200, 503)
    assert "database" in response.get_json()