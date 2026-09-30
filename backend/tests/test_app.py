from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from bedrock.core.config import Settings
from bedrock.core.db import make_engine
from bedrock.main import create_app
from bedrock.models.base import Base

from .conftest import TEST_PASSWORD


def test_requests_share_one_engine_per_app(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[Engine] = []

    def counting_make_engine(url: str) -> Engine:
        engine = make_engine(url)
        created.append(engine)
        return engine

    monkeypatch.setattr("bedrock.main.make_engine", counting_make_engine)
    app = create_app(settings=settings)

    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
        for _ in range(3):
            assert client.get("/api/v1/companies").status_code == 200

    assert len(created) == 1


def test_building_the_app_does_not_touch_the_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "not-created"
    app = create_app(settings=Settings(data_dir=data_dir))

    app.openapi()

    assert not data_dir.exists()
