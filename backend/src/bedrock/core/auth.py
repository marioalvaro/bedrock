from collections.abc import MutableMapping
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# The session cookie's payload. A session is authenticated while it holds a
# `last_seen` stamp younger than the idle limit; nothing else is stored.
SessionData = MutableMapping[str, Any]
_LAST_SEEN = "last_seen"


def verify_password(plain: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError):
        return False


class LoginThrottle:
    def __init__(self, window_minutes: int = 15, max_failures: int = 5) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._max_failures = max_failures
        # Per key: failure times within one window of the most recent failure.
        self._failures: dict[str, list[datetime]] = {}

    def is_blocked(self, key: str, now: datetime) -> bool:
        failures = self._failures.get(key)
        if not failures:
            return False
        return len(failures) >= self._max_failures and now - failures[-1] < self._window

    def record_failure(self, key: str, now: datetime) -> None:
        recent = [t for t in self._failures.get(key, []) if now - t < self._window]
        self._failures[key] = [*recent, now]

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)


class LoginResult(Enum):
    OK = "ok"
    WRONG_PASSWORD = "wrong_password"
    THROTTLED = "throttled"


def attempt_login(
    password: str, password_hash: str, throttle: LoginThrottle, key: str, now: datetime
) -> LoginResult:
    # A blocked key is refused before the password is checked, so attempts during a
    # lockout neither succeed nor extend it.
    if throttle.is_blocked(key, now):
        return LoginResult.THROTTLED
    if not verify_password(password, password_hash):
        throttle.record_failure(key, now)
        return LoginResult.WRONG_PASSWORD
    throttle.record_success(key)
    return LoginResult.OK


def start_session(session: SessionData, now: datetime) -> None:
    session[_LAST_SEEN] = now.isoformat()


def end_session(session: SessionData) -> None:
    session.clear()


def refresh_session(session: SessionData, now: datetime, idle_limit: timedelta) -> bool:
    """True, and stamps the activity, if the session is live; clears an idle one."""
    last_seen = session.get(_LAST_SEEN)
    if last_seen is None:
        return False
    if now - datetime.fromisoformat(last_seen) > idle_limit:
        end_session(session)
        return False
    start_session(session, now)
    return True
