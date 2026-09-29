from fastapi import FastAPI

from bedrock.api.v1 import companies, health
from bedrock.core.config import Settings, get_settings
from bedrock.core.db import build_get_session, get_session


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    app = FastAPI(title="Bedrock")

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(companies.router, prefix="/api/v1")

    app.dependency_overrides[get_session] = build_get_session(resolved_settings)

    return app
