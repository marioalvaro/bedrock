from collections.abc import Generator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.core.config import Settings
from bedrock.main import create_app
from bedrock.models.base import Base

TEST_PASSWORD = "test-password"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path}/bedrock.db",
        app_password_hash=PasswordHasher().hash(TEST_PASSWORD),
        session_secret="test-secret",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings=settings)


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
