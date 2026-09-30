from collections.abc import MutableMapping
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request

from bedrock.core.config import Settings, get_settings

_hasher = PasswordHasher()


def verify_password(plain: str, settings: Settings) -> bool:
    if not settings.app_password_hash:
        return False
    try:
        return _hasher.verify(settings.app_password_hash, plain)
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


def get_clock() -> datetime:
    return datetime.now(UTC)


def start_session(session: MutableMapping[str, Any], now: datetime) -> None:
    session["auth"] = True
    session["last_seen"] = now.isoformat()


def require_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_clock),
) -> None:
    session = request.session
    if not session.get("auth"):
        raise HTTPException(status_code=401)

    last_seen_raw = session.get("last_seen")
    last_seen = datetime.fromisoformat(last_seen_raw) if last_seen_raw else None
    idle_limit = timedelta(minutes=settings.session_idle_minutes)

    if last_seen is None or now - last_seen > idle_limit:
        session.clear()
        raise HTTPException(status_code=401)

    session["last_seen"] = now.isoformat()
