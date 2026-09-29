from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bedrock.core.auth import LoginThrottle, get_clock, verify_password
from bedrock.core.config import Settings

from .conftest import TEST_PASSWORD


def test_verify_password_correct() -> None:
    settings = Settings(app_password_hash=PasswordHasher().hash("secret"))
    assert verify_password("secret", settings) is True


def test_verify_password_wrong() -> None:
    settings = Settings(app_password_hash=PasswordHasher().hash("secret"))
    assert verify_password("wrong", settings) is False


def test_verify_password_empty_hash_always_fails() -> None:
    settings = Settings(app_password_hash="")
    assert verify_password("anything", settings) is False


def test_login_throttle_allows_under_max_failures() -> None:
    throttle = LoginThrottle()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(4):
        throttle.record_failure("1.2.3.4", now)
    assert throttle.is_blocked("1.2.3.4", now) is False


def test_login_throttle_blocks_after_max_failures() -> None:
    throttle = LoginThrottle()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(5):
        throttle.record_failure("1.2.3.4", now)
    assert throttle.is_blocked("1.2.3.4", now) is True


def test_login_throttle_unblocks_15min_after_last_failure() -> None:
    throttle = LoginThrottle()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(5):
        throttle.record_failure("1.2.3.4", now)
    later = now + timedelta(minutes=15, seconds=1)
    assert throttle.is_blocked("1.2.3.4", later) is False


def test_login_throttle_success_resets_count() -> None:
    throttle = LoginThrottle()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(5):
        throttle.record_failure("1.2.3.4", now)
    throttle.record_success("1.2.3.4")
    assert throttle.is_blocked("1.2.3.4", now) is False


def test_login_throttle_keys_are_independent() -> None:
    throttle = LoginThrottle()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(5):
        throttle.record_failure("1.2.3.4", now)
    assert throttle.is_blocked("5.6.7.8", now) is False


def test_login_correct_password_sets_cookie(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 204
    assert "bedrock_session" in response.cookies


def test_login_wrong_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": "nope"})
    assert response.status_code == 401


def test_login_throttled_after_five_failures(client: TestClient) -> None:
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"password": "nope"})
    response = client.post("/api/v1/auth/login", json={"password": "nope"})
    assert response.status_code == 429


def test_me_without_session(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_with_session(authed_client: TestClient) -> None:
    response = authed_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


def test_logout_then_me(authed_client: TestClient) -> None:
    response = authed_client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    response = authed_client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_idle_expiry(app: FastAPI, client: TestClient, settings: Settings) -> None:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    app.dependency_overrides[get_clock] = lambda: base_time
    login_response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    assert login_response.status_code == 204

    later = base_time + timedelta(minutes=settings.session_idle_minutes + 1)
    app.dependency_overrides[get_clock] = lambda: later
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
