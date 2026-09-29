from fastapi import Depends, FastAPI
from starlette.middleware.sessions import SessionMiddleware

from bedrock.api.v1 import auth, companies, health
from bedrock.core.auth import LoginThrottle, require_session
from bedrock.core.config import Settings, get_settings
from bedrock.core.db import build_get_session, get_session


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    app = FastAPI(title="Bedrock")
    app.state.login_throttle = LoginThrottle()

    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved_settings.session_secret,
        session_cookie="bedrock_session",
        same_site="lax",
        https_only=resolved_settings.cookie_secure,
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(companies.router, prefix="/api/v1", dependencies=[Depends(require_session)])

    app.dependency_overrides[get_session] = build_get_session(resolved_settings)
    app.dependency_overrides[get_settings] = lambda: resolved_settings

    return app
