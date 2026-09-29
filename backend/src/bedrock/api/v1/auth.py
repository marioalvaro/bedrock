from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from bedrock.core.auth import get_clock, require_session, verify_password
from bedrock.core.config import Settings, get_settings
from bedrock.schemas.auth import AuthStatus, LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", status_code=204)
def login(
    request: Request,
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_clock),
) -> None:
    throttle = request.app.state.login_throttle
    client_ip = request.client.host if request.client else "unknown"

    if throttle.is_blocked(client_ip, now):
        raise HTTPException(status_code=429)

    if not verify_password(body.password, settings):
        throttle.record_failure(client_ip, now)
        raise HTTPException(status_code=401)

    throttle.record_success(client_ip)
    request.session["auth"] = True
    request.session["last_seen"] = now.isoformat()


@router.post("/logout", status_code=204)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", dependencies=[Depends(require_session)])
def me() -> AuthStatus:
    return AuthStatus(authenticated=True)
