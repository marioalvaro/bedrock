from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from bedrock.api.deps import get_clock, get_login_throttle, get_settings
from bedrock.core.auth import LoginResult, LoginThrottle, attempt_login, end_session, start_session
from bedrock.core.config import Settings
from bedrock.schemas.auth import AuthStatus, LoginRequest

# Public: reachable without a session.
router = APIRouter(prefix="/auth", tags=["auth"])
# Mounted behind `require_session` (see api/v1/__init__.py).
session_router = APIRouter(prefix="/auth", tags=["auth"])

_FAILURE_STATUS = {LoginResult.WRONG_PASSWORD: 401, LoginResult.THROTTLED: 429}


@router.post("/login", status_code=204)
def login(
    request: Request,
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    throttle: LoginThrottle = Depends(get_login_throttle),
    now: datetime = Depends(get_clock),
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    result = attempt_login(body.password, settings.app_password_hash, throttle, client_ip, now)
    if result is not LoginResult.OK:
        raise HTTPException(status_code=_FAILURE_STATUS[result])
    start_session(request.session, now)


@router.post("/logout", status_code=204)
def logout(request: Request) -> None:
    end_session(request.session)


@session_router.get("/me")
def me() -> AuthStatus:
    return AuthStatus(authenticated=True)
