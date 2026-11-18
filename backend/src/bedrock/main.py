import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from bedrock.api.errors import register_error_handlers
from bedrock.api.v1 import api_router
from bedrock.classify import registry
from bedrock.core.auth import LoginThrottle
from bedrock.core.config import Settings, load_settings
from bedrock.core.db import make_engine, make_sessionmaker
from bedrock.core.scheduler import acquire_scheduler_lock, refresh_loop
from bedrock.core.spa import mount_spa
from bedrock.ingest.sources import Sources, build_sources
from bedrock.services.classification import ClassificationRunner
from bedrock.services.filings import BackfillRunner
from bedrock.services.statements import use_classification_threshold


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Opened at startup rather than in create_app, so building the app (e.g. to
    # export the OpenAPI schema) never touches the database.
    engine = make_engine(app.state.settings.resolved_database_url)
    app.state.engine = engine
    app.state.session_factory = make_sessionmaker(engine)
    refresher = None
    # One loop per deployment: of several workers, only the lock holder runs it.
    lock = (
        acquire_scheduler_lock(app.state.settings.data_dir)
        if app.state.settings.scheduled_refresh
        else None
    )
    if lock is not None:
        refresher = asyncio.create_task(
            refresh_loop(
                app.state.session_factory,
                app.state.sources,
                data_dir=app.state.settings.data_dir,
            )
        )
    try:
        yield
    finally:
        if refresher is not None:
            refresher.cancel()
            with suppress(asyncio.CancelledError):
                await refresher
        if lock is not None:
            lock.close()
        engine.dispose()


def create_app(settings: Settings | None = None, *, sources: Sources | None = None) -> FastAPI:
    settings = settings or load_settings()

    app = FastAPI(title="Bedrock", lifespan=lifespan)
    app.state.settings = settings
    # Building real sources makes no network call; tests pass fakes built from the fixtures.
    app.state.sources = sources or build_sources(settings)
    app.state.login_throttle = LoginThrottle()
    app.state.backfills = BackfillRunner()
    # Building a classifier makes no request; only a confirmed run does (tests replace it).
    app.state.classifier_factory = registry.get
    app.state.classifications = ClassificationRunner()
    use_classification_threshold(settings.classify_min_confidence)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="bedrock_session",
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    register_error_handlers(app)
    app.include_router(api_router)

    if settings.static_dir is not None:
        mount_spa(app, settings.static_dir)

    return app
