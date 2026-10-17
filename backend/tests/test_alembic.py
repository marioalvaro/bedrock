from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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
    qoe_custom_rule,
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
    qoe_custom_rule,
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


_NOW = "2026-10-17 00:00:00"


def _insert_threshold(connection: Connection, rule: str, **cols: object) -> None:
    names = ", ".join(["rule_code", "updated_at", *cols])
    marks = ", ".join(f":{k}" for k in ["rule_code", "updated_at", *cols])
    connection.execute(
        text(f"INSERT INTO qoe_threshold ({names}) VALUES ({marks})"),
        {"rule_code": rule, "updated_at": _NOW, **cols},
    )


def _insert_rule(connection: Connection, **cols: object) -> None:
    base = {
        "label": "L",
        "formula": "a / b",
        "direction": "above",
        "unit": "pct",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row = {**base, **cols}
    names = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    connection.execute(text(f"INSERT INTO qoe_custom_rule ({names}) VALUES ({marks})"), row)


def test_0004_adds_custom_rule_table_and_formula_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    columns = {c["name"] for c in inspector.get_columns("qoe_custom_rule")}
    assert columns == {
        "id", "label", "formula", "direction", "unit", "warn", "alert",
        "warn_formula", "alert_formula", "created_at", "updated_at",
    }  # fmt: skip
    threshold_columns = {c["name"] for c in inspector.get_columns("qoe_threshold")}
    assert {"warn_formula", "alert_formula"} <= threshold_columns


def test_0004_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    for level in ("warn", "alert"):
        both = {level: 1, f"{level}_formula": "x"}
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_threshold(connection, "r_both", **both)
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_rule(connection, **both)
    for bad in ({"direction": "sideways"}, {"unit": "usd"}):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_rule(connection, **bad)
    with engine.begin() as connection:
        _insert_threshold(connection, "r_num", warn=1)
        _insert_threshold(connection, "r_formula", warn_formula="x")
        _insert_rule(connection, warn=1, alert_formula="y")
        _insert_rule(connection, warn_formula="x", alert=2)


def test_0004_keeps_threshold_rows_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0003"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _insert_threshold(connection, "r_old", warn=1.5, alert=3)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    select = text("SELECT warn, alert FROM qoe_threshold WHERE rule_code = 'r_old'")
    with engine.connect() as connection:
        assert tuple(map(float, connection.execute(select).one())) == (1.5, 3.0)
    with engine.begin() as connection:
        _insert_threshold(connection, "r_new", warn_formula="x")

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0003"))
    inspector = inspect(engine)
    assert "qoe_custom_rule" not in inspector.get_table_names()
    assert not {"warn_formula", "alert_formula"} & {
        c["name"] for c in inspector.get_columns("qoe_threshold")
    }
    with engine.connect() as connection:
        assert tuple(map(float, connection.execute(select).one())) == (1.5, 3.0)
