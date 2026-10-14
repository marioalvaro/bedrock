from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from bedrock.core.config import load_settings
from bedrock.models import (
    adjustment,
    canonical_item,
    company,
    concept_mapping,
    corporate_action,
    filing,
    off_balance_item,
    price_daily,
    qoe_threshold,
    raw_fact,
)
from bedrock.models.base import Base

# Importing registers every table on Base.metadata, so the drift test below sees them all.
_MODELS = (
    adjustment,
    canonical_item,
    company,
    concept_mapping,
    corporate_action,
    filing,
    off_balance_item,
    price_daily,
    qoe_threshold,
    raw_fact,
)


def test_alembic_upgrade_head_creates_company_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "bedrock.db"
    database_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-secret")  # required by Settings; CI has no .env
    load_settings.cache_clear()

    backend_dir = Path(__file__).resolve().parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))

    try:
        command.upgrade(config, "head")
    finally:
        load_settings.cache_clear()

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "company" in inspector.get_table_names()


def test_upgrade_head_creates_the_data_layer_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {"filing", "raw_fact", "canonical_item", "concept_mapping", "price_daily"} <= tables


def _run_alembic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *steps: tuple[str, str]) -> str:
    database_url = f"sqlite:///{tmp_path / 'bedrock.db'}"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-secret")  # required by Settings; CI has no .env
    load_settings.cache_clear()

    backend_dir = Path(__file__).resolve().parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    try:
        for action, revision in steps:
            getattr(command, action)(config, revision)
    finally:
        load_settings.cache_clear()
    return database_url


def test_migrations_match_the_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A model change without a migration would pass every TestClient test
    # (they use create_all) and only break the real DB in Docker.
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))

    with create_engine(database_url).connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert diff == []


def test_downgrade_to_base_removes_the_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"), ("downgrade", "base"))
    assert inspect(create_engine(database_url)).get_table_names() == ["alembic_version"]


_ANALYSIS_TABLES = {"adjustment", "corporate_action", "off_balance_item", "qoe_threshold"}


def test_upgrade_head_creates_the_analysis_tables_and_downgrade_removes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    assert _ANALYSIS_TABLES <= set(inspector.get_table_names())
    uq = {
        table: {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table)}
        for table in ("corporate_action", "qoe_threshold")
    }
    assert ("company_id", "effective_date") in uq["corporate_action"]
    assert ("rule_code",) in uq["qoe_threshold"]

    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"), ("downgrade", "0002"))
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert not _ANALYSIS_TABLES & tables
    assert "price_daily" in tables
