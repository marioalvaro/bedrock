import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from bedrock.cli import app
from bedrock.core.config import load_settings
from bedrock.core.db import make_engine
from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.base import Base
from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.company import Company

from .fakes import FakeEdgar, FakePrices
from .seed import fake_sources

runner = CliRunner()


def test_hash_password_output_verifies() -> None:
    result = runner.invoke(app, ["hash-password"], input="test-password\ntest-password\n")
    assert result.exit_code == 0
    hashed = result.stdout.strip().splitlines()[-1]

    PasswordHasher().verify(hashed, "test-password")


def test_export_openapi_writes_valid_json_with_companies_path(tmp_path: Path) -> None:
    out_path = tmp_path / "openapi.json"
    result = runner.invoke(app, ["export-openapi", str(out_path)])
    assert result.exit_code == 0

    schema = json.loads(out_path.read_text())
    assert "/api/v1/companies" in schema["paths"]


def test_hash_password_mismatch_exits_nonzero_without_a_hash() -> None:
    result = runner.invoke(app, ["hash-password"], input="first-pass\nsecond-pass\n")
    assert result.exit_code == 1
    assert "$argon2" not in result.stdout


def test_export_openapi_needs_no_session_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CI exports the schema with no .env; building it never signs a cookie.
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)
    out_path = tmp_path / "openapi.json"
    result = runner.invoke(app, ["export-openapi", str(out_path)])
    assert result.exit_code == 0, result.output
    assert "/api/v1/auth/me" in json.loads(out_path.read_text())["paths"]


# --- add / refresh / sync-mappings ------------------------------------------------------------


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A migrated-looking temporary database, the fake sources, and no `.env` in reach."""
    db = tmp_path / "cli.db"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    load_settings.cache_clear()
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setattr("bedrock.cli.build_sources", lambda settings: fake_sources())
    yield db
    load_settings.cache_clear()


def _tickers(db: Path) -> list[str]:
    engine = make_engine(f"sqlite:///{db}")
    with Session(engine) as session:
        found = list(session.execute(select(Company.ticker).order_by(Company.ticker)).scalars())
    engine.dispose()
    return found


def test_add_follows_each_ticker_and_prints_what_was_loaded(cli_db: Path) -> None:
    result = runner.invoke(app, ["add", "AAPL", "msft"])

    assert result.exit_code == 0, result.output
    assert _tickers(cli_db) == ["AAPL", "MSFT"]
    assert "AAPL" in result.output and "MSFT" in result.output


def test_add_goes_on_after_a_failure_and_exits_1(cli_db: Path) -> None:
    result = runner.invoke(app, ["add", "ZZZZ", "AAPL"])

    assert result.exit_code == 1
    assert "ZZZZ" in result.output
    assert _tickers(cli_db) == ["AAPL"]


def test_add_of_a_followed_company_fails_with_the_reason(cli_db: Path) -> None:
    runner.invoke(app, ["add", "AAPL"])

    result = runner.invoke(app, ["add", "AAPL"])

    assert result.exit_code == 1
    assert "already followed" in result.output


def test_refresh_prints_the_result_of_each_ticker(cli_db: Path) -> None:
    runner.invoke(app, ["add", "AAPL", "MSFT"])

    result = runner.invoke(app, ["refresh", "AAPL"])

    assert result.exit_code == 0, result.output
    assert "AAPL" in result.output and "MSFT" not in result.output
    for line in (
        "new_filings: 0",
        "new_facts: 0",
        "new_prices: 0",
        "new_splits: 0",
        "last_refreshed_at:",
    ):
        assert line in result.output


def test_refresh_all_covers_every_followed_company(cli_db: Path) -> None:
    runner.invoke(app, ["add", "AAPL", "MSFT"])

    result = runner.invoke(app, ["refresh", "--all"])

    assert result.exit_code == 0, result.output
    assert "AAPL" in result.output and "MSFT" in result.output


def test_refresh_needs_tickers_or_all(cli_db: Path) -> None:
    result = runner.invoke(app, ["refresh"])

    assert result.exit_code == 2


def test_refresh_of_an_unfollowed_company_exits_1(cli_db: Path) -> None:
    result = runner.invoke(app, ["refresh", "AAPL"])

    assert result.exit_code == 1
    assert "not a followed company" in result.output


def test_refresh_exits_1_when_a_source_fails_but_still_tries_the_rest(
    cli_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(app, ["add", "AAPL", "MSFT"])
    edgar = FakeEdgar(fetch_raises=SourceUnavailable("sec.gov is down"))
    monkeypatch.setattr("bedrock.cli.build_sources", lambda s: Sources(edgar, FakePrices()))

    result = runner.invoke(app, ["refresh", "--all"])

    assert result.exit_code == 1
    assert "sec.gov is down" in result.output
    assert "AAPL" in result.output and "MSFT" in result.output  # both were attempted


def test_sync_mappings_stores_the_canonical_items(cli_db: Path) -> None:
    result = runner.invoke(app, ["sync-mappings"])

    assert result.exit_code == 0, result.output
    engine = make_engine(f"sqlite:///{cli_db}")
    with Session(engine) as session:
        assert session.execute(select(func.count()).select_from(CanonicalItem)).scalar_one() == 78
    engine.dispose()
