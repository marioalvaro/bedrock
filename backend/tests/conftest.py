import shutil
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from bedrock.core.config import Settings
from bedrock.ingest.sources import Sources
from bedrock.main import create_app
from bedrock.models.base import Base

from .fakes import FakeEdgar, FakePrices

TEST_PASSWORD = "test-password"

# A real argon2 hash, but with the cheapest parameters: `verify` reads them from the hash string,
# so login still runs the production code path at ~1 ms instead of ~30 ms per test. Hashed once.
_TEST_PASSWORD_HASH = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(TEST_PASSWORD)


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
        app_password_hash=_TEST_PASSWORD_HASH,
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


@pytest.fixture(scope="session")
def _followed_db_cache(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, ...], Path]:
    return {}


def _followed_db(
    tickers: tuple[str, ...],
    cache: dict[tuple[str, ...], Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """The database after following `tickers` through the API, built once per session and then
    copied for each test: ingesting a recorded filing (~0.7 s a company) is the dominant cost of
    the suite, and every test still gets its own private copy."""
    if tickers not in cache:
        root = tmp_path_factory.mktemp("followed-" + "-".join(tickers))
        built = Settings(
            _env_file=None,
            data_dir=root,
            database_url=f"sqlite:///{root}/bedrock.db",
            sec_user_agent=None,
            fred_api_key=None,
            app_password_hash=_TEST_PASSWORD_HASH,
            session_secret="test-secret",
            session_idle_minutes=720,
            cookie_secure=False,
            static_dir=None,
        )
        app = create_app(settings=built, sources=Sources(edgar=FakeEdgar(), prices=FakePrices()))
        with TestClient(app) as seeding:
            Base.metadata.create_all(app.state.engine)
            login = seeding.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
            assert login.status_code == 204
            for ticker in tickers:
                response = seeding.post("/api/v1/companies", json={"ticker": ticker})
                assert response.status_code == 201, response.text
        cache[tickers] = root / "bedrock.db"  # the engine is disposed: no WAL left behind
    return cache[tickers]


@pytest.fixture
def seed_db(
    app: FastAPI,
    settings: Settings,
    _followed_db_cache: dict[tuple[str, ...], Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[..., None]:
    """`seed_db("AAPL", "MSFT")`: start this test's database as if those companies had just been
    followed through `POST /companies` (in that order). Safe to call whether or not the client has
    started (fixture order follows the test's argument order), as long as nothing is followed
    yet: it swaps the database file under the app, which is only valid on an untouched one."""

    def seed(*tickers: str) -> None:
        template = _followed_db(tickers, _followed_db_cache, tmp_path_factory)
        target = settings.data_dir / "bedrock.db"
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            with engine.connect() as connection:
                followed = connection.execute(text("SELECT count(*) FROM company")).scalar_one()
            assert followed == 0, "seed_db needs a database with no followed company"
            engine.dispose()  # drop pooled connections to the file about to be replaced
            for suffix in ("-wal", "-shm"):
                Path(f"{target}{suffix}").unlink(missing_ok=True)
        shutil.copyfile(template, target)

    return seed


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
