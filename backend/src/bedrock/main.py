from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from bedrock.api.v1 import api_router
from bedrock.core.auth import LoginThrottle
from bedrock.core.config import Settings, load_settings
from bedrock.core.db import make_engine, make_sessionmaker
from bedrock.core.spa import mount_spa


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Opened at startup rather than in create_app, so building the app (e.g. to
    # export the OpenAPI schema) never touches the database.
    engine = make_engine(app.state.settings.resolved_database_url)
    app.state.engine = engine
    app.state.session_factory = make_sessionmaker(engine)
    try:
        yield
    finally:
        engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    app = FastAPI(title="Bedrock", lifespan=lifespan)
    app.state.settings = settings
    app.state.login_throttle = LoginThrottle()

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="bedrock_session",
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    app.include_router(api_router)

    if settings.static_dir is not None:
        mount_spa(app, settings.static_dir)

    return app
