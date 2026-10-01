from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from bedrock.api.deps import get_clock
from bedrock.core.auth import (
    LoginResult,
    LoginThrottle,
    attempt_login,
    end_session,
    refresh_session,
    start_session,
    verify_password,
)
from bedrock.core.config import Settings
from bedrock.main import create_app

from .conftest import TEST_PASSWORD

SECRET_HASH = PasswordHasher().hash("secret")
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
IDLE = timedelta(minutes=720)


def test_verify_password_correct() -> None:
    assert verify_password("secret", SECRET_HASH) is True


def test_verify_password_wrong() -> None:
    assert verify_password("wrong", SECRET_HASH) is False


def test_verify_password_empty_hash_always_fails() -> None:
    assert verify_password("anything", "") is False


def test_attempt_login_correct_password_is_ok() -> None:
    assert attempt_login("secret", SECRET_HASH, LoginThrottle(), "ip", NOW) is LoginResult.OK


def test_attempt_login_wrong_password_records_a_failure() -> None:
    throttle = LoginThrottle()
    for _ in range(5):
        result = attempt_login("nope", SECRET_HASH, throttle, "ip", NOW)
        assert result is LoginResult.WRONG_PASSWORD
    assert throttle.is_blocked("ip", NOW) is True


def test_attempt_login_while_blocked_is_throttled_even_with_the_right_password() -> None:
    throttle = LoginThrottle()
    for _ in range(5):
        throttle.record_failure("ip", NOW)
    assert attempt_login("secret", SECRET_HASH, throttle, "ip", NOW) is LoginResult.THROTTLED


def test_attempt_login_success_resets_the_failures() -> None:
    throttle = LoginThrottle()
    for _ in range(4):
        throttle.record_failure("ip", NOW)
    attempt_login("secret", SECRET_HASH, throttle, "ip", NOW)
    throttle.record_failure("ip", NOW)
    assert throttle.is_blocked("ip", NOW) is False


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


def test_login_throttle_only_counts_failures_within_window() -> None:
    throttle = LoginThrottle()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for day in range(5):
        throttle.record_failure("1.2.3.4", start + timedelta(days=day))
    assert throttle.is_blocked("1.2.3.4", start + timedelta(days=4, minutes=1)) is False


def test_login_throttle_single_failure_after_lockout_does_not_reblock() -> None:
    throttle = LoginThrottle()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(5):
        throttle.record_failure("1.2.3.4", now)
    later = now + timedelta(minutes=16)
    throttle.record_failure("1.2.3.4", later)
    assert throttle.is_blocked("1.2.3.4", later) is False


def test_login_throttle_blocks_five_failures_just_inside_window() -> None:
    throttle = LoginThrottle()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for minute in (0, 4, 8, 12, 14):
        throttle.record_failure("1.2.3.4", start + timedelta(minutes=minute))
    assert throttle.is_blocked("1.2.3.4", start + timedelta(minutes=14)) is True


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


def test_start_session_stamps_activity() -> None:
    session: dict[str, object] = {}
    start_session(session, NOW)
    assert session == {"last_seen": NOW.isoformat()}


def test_refresh_session_rejects_a_session_never_started() -> None:
    session: dict[str, object] = {}
    assert refresh_session(session, NOW, IDLE) is False


def test_refresh_session_accepts_a_live_session_and_stamps_activity() -> None:
    session: dict[str, object] = {}
    start_session(session, NOW)
    later = NOW + IDLE - timedelta(minutes=1)
    assert refresh_session(session, later, IDLE) is True
    assert session == {"last_seen": later.isoformat()}


def test_refresh_session_clears_an_idle_session() -> None:
    session: dict[str, object] = {}
    start_session(session, NOW)
    assert refresh_session(session, NOW + IDLE + timedelta(seconds=1), IDLE) is False
    assert session == {}


def test_end_session_clears_it() -> None:
    session: dict[str, object] = {}
    start_session(session, NOW)
    end_session(session)
    assert refresh_session(session, NOW, IDLE) is False


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


def test_activity_refreshes_idle_timeout(
    app: FastAPI, client: TestClient, settings: Settings
) -> None:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    idle = timedelta(minutes=settings.session_idle_minutes)
    app.dependency_overrides[get_clock] = lambda: base_time
    assert client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD}).status_code == 204

    active_at = base_time + idle - timedelta(minutes=1)
    app.dependency_overrides[get_clock] = lambda: active_at
    assert client.get("/api/v1/auth/me").status_code == 200

    # Past the idle limit counted from login, but within it counted from the last request.
    later = base_time + idle + timedelta(minutes=1)
    app.dependency_overrides[get_clock] = lambda: later
    assert client.get("/api/v1/auth/me").status_code == 200


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def _set_cookie(response: Response) -> str:
    return response.headers["set-cookie"].lower()


def test_session_cookie_is_httponly_lax_and_not_secure_by_default(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    cookie = _set_cookie(response)
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie


def test_cookie_secure_setting_marks_the_session_cookie_secure(settings: Settings) -> None:
    app = create_app(settings=settings.model_copy(update={"cookie_secure": True}))
    with TestClient(app) as secure_client:
        response = secure_client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    assert "secure" in _set_cookie(response)


def test_session_cookie_signed_with_another_secret_is_rejected(settings: Settings) -> None:
    other = create_app(settings=settings.model_copy(update={"session_secret": "other-secret"}))
    with TestClient(other) as other_client:
        other_client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
        forged = other_client.cookies["bedrock_session"]

    with TestClient(create_app(settings=settings)) as client:
        client.cookies.set("bedrock_session", forged)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_correct_password_while_throttled_is_still_429(client: TestClient) -> None:
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"password": "nope"})
    response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 429
    assert client.get("/api/v1/auth/me").status_code == 401


def test_successful_login_resets_the_failure_count(client: TestClient) -> None:
    for _ in range(4):
        client.post("/api/v1/auth/login", json={"password": "nope"})
    assert client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD}).status_code == 204
    for _ in range(4):
        client.post("/api/v1/auth/login", json={"password": "nope"})
    response = client.post("/api/v1/auth/login", json={"password": "nope"})
    assert response.status_code == 401


def test_attempts_during_lockout_do_not_extend_it(app: FastAPI, client: TestClient) -> None:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    app.dependency_overrides[get_clock] = lambda: start
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"password": "nope"})

    during = start + timedelta(minutes=10)
    app.dependency_overrides[get_clock] = lambda: during
    assert client.post("/api/v1/auth/login", json={"password": "nope"}).status_code == 429

    # 15 min after the last *real* failure, not after the blocked attempt.
    after = start + timedelta(minutes=15, seconds=1)
    app.dependency_overrides[get_clock] = lambda: after
    response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 204


def test_idle_expiry_clears_the_session(
    app: FastAPI, client: TestClient, settings: Settings
) -> None:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    app.dependency_overrides[get_clock] = lambda: base_time
    assert client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD}).status_code == 204

    later = base_time + timedelta(minutes=settings.session_idle_minutes + 1)
    app.dependency_overrides[get_clock] = lambda: later
    assert client.get("/api/v1/auth/me").status_code == 401

    # The expired session is gone, not just rejected at that moment.
    app.dependency_overrides[get_clock] = lambda: base_time
    assert client.get("/api/v1/auth/me").status_code == 401
