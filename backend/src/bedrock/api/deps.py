"""Request-scoped FastAPI dependencies: the bridge from `app.state` and the session
cookie to the pure core."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from bedrock.core.auth import LoginThrottle, refresh_session
from bedrock.core.config import Settings
from bedrock.ingest.sources import Sources
from bedrock.services.classification import ClassificationRunner, Factory
from bedrock.services.filings import BackfillRunner


def get_settings(request: Request) -> Settings:
    """The settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Generator[Session, None, None]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """For work that outlives the request (a backfill's worker thread opens its own session)."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    return session_factory


def get_backfills(request: Request) -> BackfillRunner:
    backfills: BackfillRunner = request.app.state.backfills
    return backfills


def get_classifications(request: Request) -> ClassificationRunner:
    runner: ClassificationRunner = request.app.state.classifications
    return runner


def get_classifier_factory(request: Request) -> Factory:
    """What builds a classifier for a run (`classify/registry.py::get`; tests replace it)."""
    factory: Factory = request.app.state.classifier_factory
    return factory


def get_sources(request: Request) -> Sources:
    sources: Sources = request.app.state.sources
    return sources


def get_login_throttle(request: Request) -> LoginThrottle:
    throttle: LoginThrottle = request.app.state.login_throttle
    return throttle


def get_clock() -> datetime:
    return datetime.now(UTC)


def require_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_clock),
) -> None:
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if not refresh_session(request.session, now, idle_limit):
        raise HTTPException(status_code=401)
