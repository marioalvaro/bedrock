from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from bedrock.core.config import Settings
from bedrock.core.db import make_engine
from bedrock.ingest.sources import Sources, build_sources
from bedrock.main import create_app
from bedrock.models.base import Base

from .conftest import TEST_PASSWORD
from .fakes import FakeEdgar, FakePrices


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
    # database_url pinned to None so the DB really would live under data_dir; with
    # DATABASE_URL set elsewhere (e.g. the dev container) this test proved nothing.
    app = create_app(
        settings=Settings(
            _env_file=None, data_dir=data_dir, database_url=None, session_secret="test-secret"
        )
    )

    app.openapi()

    assert not data_dir.exists()


def test_the_app_holds_the_sources_it_was_given(settings: Settings) -> None:
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices())

    app = create_app(settings=settings, sources=sources)

    assert app.state.sources is sources


def test_the_app_builds_real_sources_by_default_without_a_network_call(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[Settings] = []

    def recording_build_sources(given: Settings) -> Sources:
        built.append(given)
        return build_sources(given)

    monkeypatch.setattr("bedrock.main.build_sources", recording_build_sources)

    app = create_app(settings=settings)

    assert built == [settings]
    assert isinstance(app.state.sources, Sources)
