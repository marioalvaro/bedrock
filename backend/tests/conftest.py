from collections.abc import Generator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.core.config import Settings
from bedrock.ingest.sources import Sources
from bedrock.main import create_app
from bedrock.models.base import Base

from .fakes import FakeEdgar, FakePrices

TEST_PASSWORD = "test-password"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Every field pinned, and no .env read: init values beat env vars, so nothing in
    # the developer's environment can change what the suite tests (G11).
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path}/bedrock.db",
        sec_user_agent=None,
        fred_api_key=None,
        app_password_hash=PasswordHasher().hash(TEST_PASSWORD),
        session_secret="test-secret",
        session_idle_minutes=720,
        cookie_secure=False,
        static_dir=None,
    )


@pytest.fixture
def fake_edgar() -> FakeEdgar:
    return FakeEdgar()


@pytest.fixture
def fake_prices() -> FakePrices:
    return FakePrices()


@pytest.fixture
def app(settings: Settings, fake_edgar: FakeEdgar, fake_prices: FakePrices) -> FastAPI:
    return create_app(settings=settings, sources=Sources(edgar=fake_edgar, prices=fake_prices))


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    # Entering the client runs the lifespan, which opens the app's engine.
    with TestClient(app) as test_client:
        Base.metadata.create_all(app.state.engine)
        yield test_client


@pytest.fixture
def db_session(app: FastAPI, client: TestClient) -> Generator[Session, None, None]:
    """A session on the running app's own database."""
    with app.state.session_factory() as session:
        yield session


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 204
    return client
