from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.core.config import Settings
from bedrock.core.db import make_engine, make_sessionmaker
from bedrock.main import create_app
from bedrock.models.base import Base


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path}/bedrock.db")


@pytest.fixture
def db_session(settings: Settings) -> Generator[Session, None, None]:
    engine = make_engine(settings.resolved_database_url)
    Base.metadata.create_all(engine)
    session_factory = make_sessionmaker(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(settings: Settings, db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client
