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
    audit_log,
    canonical_item,
    classification_run,
    company,
    comps_member,
    comps_set,
    concept_mapping,
    consensus_estimate,
    corporate_action,
    custom_line,
    driver_value,
    filing,
    filing_line,
    forecast_run,
    guidance,
    imported_fact,
    line_classification,
    macro,
    note,
    off_balance_item,
    pending_filing,
    price_daily,
    qoe_custom_rule,
    qoe_threshold,
    raw_fact,
    scenario,
    segment_series,
    segment_value,
    statement_import,
    thesis_checkpoint,
    valuation_input,
)
from bedrock.models.base import Base

# Importing registers every table on Base.metadata, so the drift test below sees them all.
_MODELS = (
    adjustment,
    audit_log,
    canonical_item,
    classification_run,
    company,
    comps_member,
    comps_set,
    concept_mapping,
    consensus_estimate,
    corporate_action,
    custom_line,
    driver_value,
    filing,
    filing_line,
    forecast_run,
    guidance,
    imported_fact,
    line_classification,
    macro,
    note,
    off_balance_item,
    pending_filing,
    price_daily,
    qoe_custom_rule,
    qoe_threshold,
    raw_fact,
    scenario,
    segment_series,
    segment_value,
    statement_import,
    thesis_checkpoint,
    valuation_input,
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


_CONTEXT_TABLES = {
    "segment_series",
    "segment_value",
    "comps_set",
    "comps_member",
    "guidance",
    "note",
}


def _insert(connection: Connection, table: str, **cols: object) -> int:
    names = ", ".join(cols)
    marks = ", ".join(f":{k}" for k in cols)
    result = connection.execute(text(f"INSERT INTO {table} ({names}) VALUES ({marks})"), cols)
    return int(result.lastrowid)


def _company(connection: Connection, ticker: str) -> int:
    return _insert(
        connection,
        "company",
        ticker=ticker,
        cik=f"cik-{ticker}",
        name=ticker,
        fiscal_year_end_month=12,
        currency="USD",
    )


def _series(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "dimension": "business",
        "name": "Cloud",
        "metric": "revenue",
        "unit": "USD",
        "display_order": 0,
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "segment_series", **row)


def _value(connection: Connection, series_id: int, **cols: object) -> int:
    row = {
        "series_id": series_id,
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "value": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "segment_value", **row)


def _guidance(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "metric": "revenue",
        "fiscal_year": 2026,
        "fiscal_period": "FY",
        "low": 1,
        "high": 2,
        "basis": "reported",
        "direction": "higher",
        "given_on": "2026-01-01",
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "guidance", **row)


def _note(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "body_md": "x",
        "note_date": "2026-01-01",
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "note", **row)


def _comps_set(connection: Connection, company_id: int, name: str = "Peers") -> int:
    return _insert(
        connection, "comps_set", company_id=company_id, name=name, created_at=_NOW, updated_at=_NOW
    )


def test_0005_upgrade_creates_context_tables_and_downgrade_removes_only_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    assert _CONTEXT_TABLES <= set(inspector.get_table_names())
    uq = {
        table: {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table)}
        for table in ("segment_series", "segment_value", "comps_set", "comps_member")
    }
    assert ("company_id", "dimension", "name", "metric") in uq["segment_series"]
    assert ("series_id", "fiscal_year", "fiscal_period") in uq["segment_value"]
    assert ("company_id", "name") in uq["comps_set"]
    assert ("comps_set_id", "peer_company_id") in uq["comps_member"]

    database_url = _run_alembic(tmp_path, monkeypatch, ("downgrade", "0004"))
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert not _CONTEXT_TABLES & tables
    assert {"company", "qoe_custom_rule", "qoe_threshold", "price_daily"} <= tables


def test_0005_uniques_reject_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        peer_id = _company(connection, "BBB")
        series_id = _series(connection, company_id)
        _value(connection, series_id)
        set_id = _comps_set(connection, company_id)
        _insert(connection, "comps_member", comps_set_id=set_id, peer_company_id=peer_id)
    duplicates = (
        lambda c: _series(c, company_id),
        lambda c: _value(c, series_id),
        lambda c: _comps_set(c, company_id),
        lambda c: _insert(c, "comps_member", comps_set_id=set_id, peer_company_id=peer_id),
    )
    for duplicate in duplicates:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            duplicate(connection)


def test_0005_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        series_id = _series(connection, company_id)
    bad_rows = (
        lambda c: _guidance(c, company_id, low=3, high=2),
        lambda c: _guidance(c, company_id, basis="gaap"),
        lambda c: _guidance(c, company_id, direction="up"),
        lambda c: _guidance(c, company_id, fiscal_period="Q5"),
        lambda c: _note(c, company_id, fiscal_year=2025),
        lambda c: _note(c, company_id, fiscal_period="FY"),
        lambda c: _note(c, company_id, fiscal_year=2025, fiscal_period="H1"),
        lambda c: _series(c, company_id, name="Other", dimension="region"),
        lambda c: _series(c, company_id, name="Other", unit="EUR"),
        lambda c: _value(c, series_id, fiscal_year=2024, fiscal_period="H1"),
    )
    for bad in bad_rows:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            bad(connection)
    with engine.begin() as connection:
        _guidance(connection, company_id, low=2, high=2, basis="normalized", direction="lower")
        _note(connection, company_id)
        _note(connection, company_id, fiscal_year=2025, fiscal_period="Q4")


def test_0005_foreign_keys_cascade_on_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        owner = _company(connection, "AAA")
        peer = _company(connection, "BBB")
        series_id = _series(connection, owner)
        _value(connection, series_id)
        set_id = _comps_set(connection, owner)
        _insert(connection, "comps_member", comps_set_id=set_id, peer_company_id=peer)
        _guidance(connection, owner)
        _note(connection, owner)

        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": peer})
        assert connection.execute(text("SELECT count(*) FROM comps_member")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM comps_set")).scalar() == 1

        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": owner})
        for table in sorted(_CONTEXT_TABLES):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table


def test_0005_creates_fk_indexes_and_the_partial_unique_kpi_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    for table, column in (
        ("guidance", "company_id"),
        ("note", "company_id"),
        ("comps_member", "peer_company_id"),
    ):
        indexes = {i["name"]: i for i in inspector.get_indexes(table)}
        assert indexes[f"ix_{table}_{column}"]["column_names"] == [column]
    kpi = {i["name"]: i for i in inspector.get_indexes("segment_series")}[
        "uq_segment_series_kpi_code"
    ]
    assert kpi["unique"]
    assert kpi["column_names"] == ["company_id", "metric"]

    database_url = _run_alembic(tmp_path, monkeypatch, ("downgrade", "0004"))
    assert not _CONTEXT_TABLES & set(inspect(create_engine(database_url)).get_table_names())


def test_0005_kpi_code_is_unique_per_company_among_kpi_series_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        first = _company(connection, "AAA")
        second = _company(connection, "BBB")
        _series(connection, first, dimension="kpi", name="Stores", metric="stores")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _series(connection, first, dimension="kpi", name="Store count", metric="stores")
    with engine.begin() as connection:
        _series(connection, first, dimension="business", name="Stores", metric="stores")
        _series(connection, first, dimension="geo", name="Stores", metric="stores")
        _series(connection, second, dimension="kpi", name="Stores", metric="stores")


def test_0006_adds_metric_link_columns_and_index_and_downgrade_keeps_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    columns = {c["name"]: c for c in inspector.get_columns("note")}
    assert columns["metric_kind"]["nullable"]
    assert columns["metric_code"]["nullable"]
    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("note")}
    assert indexes["ix_note_company_metric"] == ["company_id", "metric_kind", "metric_code"]

    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        _note(connection, company_id, metric_kind="ratio", metric_code="roe")
        _note(connection, company_id, canonical_code="revenue")

    database_url = _run_alembic(tmp_path, monkeypatch, ("downgrade", "0005"))
    inspector = inspect(create_engine(database_url))
    assert {c["name"] for c in inspector.get_columns("note")} & {
        "metric_kind",
        "metric_code",
    } == set()
    with create_engine(database_url).connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM note")).scalar_one() == 2


def test_0006_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
    bad_rows = (
        lambda c: _note(c, company_id, metric_kind="ratio"),
        lambda c: _note(c, company_id, metric_code="roe"),
        lambda c: _note(c, company_id, metric_kind="valuation", metric_code="roe"),
        lambda c: _note(
            c, company_id, canonical_code="revenue", metric_kind="ratio", metric_code="roe"
        ),
    )
    for bad in bad_rows:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            bad(connection)
    with engine.begin() as connection:
        _note(connection, company_id, metric_kind="capital", metric_code="capex")
        _note(
            connection,
            company_id,
            metric_kind="quality",
            metric_code="custom_3",
            fiscal_year=2025,
            fiscal_period="FY",
        )


_IMPORT_TABLES = {"statement_import", "imported_fact", "custom_line"}


def _import(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "filename": "aapl.xlsx",
        "format": "xlsx",
        "scale": "millions",
        "imported_at": _NOW,
        "cells": 1,
        **cols,
    }
    return _insert(connection, "statement_import", **row)


def _imported_fact(connection: Connection, import_id: int, company_id: int, **cols: object) -> int:
    row = {
        "import_id": import_id,
        "company_id": company_id,
        "line_code": "revenue",
        "fiscal_year": 2006,
        "fiscal_period": "FY",
        "period_start": "2005-09-26",
        "period_end": "2006-09-30",
        "value": 1,
        **cols,
    }
    return _insert(connection, "imported_fact", **row)


def _custom_line(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "code": "custom:products",
        "label": "Products",
        "statement": "IS",
        "parent_code": "cost_of_revenue",
        "kind": "flow",
        "unit": "USD",
        "children_complete": 0,
        "display_order": 1,
        **cols,
    }
    return _insert(connection, "custom_line", **row)


def test_0007_upgrade_creates_the_import_tables_and_downgrade_removes_only_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    assert _IMPORT_TABLES <= set(inspector.get_table_names())
    uq = {
        table: {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table)}
        for table in ("imported_fact", "custom_line")
    }
    assert ("import_id", "line_code", "fiscal_year", "fiscal_period") in uq["imported_fact"]
    assert ("company_id", "code") in uq["custom_line"]
    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("imported_fact")}
    assert indexes["ix_imported_fact_company_line"] == [
        "company_id",
        "line_code",
        "fiscal_year",
        "fiscal_period",
    ]
    assert inspector.get_indexes("statement_import")[0]["column_names"] == ["company_id"]

    database_url = _run_alembic(tmp_path, monkeypatch, ("downgrade", "0006"))
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert not _IMPORT_TABLES & tables
    assert {"company", "note", "segment_series"} <= tables


def test_0007_uniques_and_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        import_id = _import(connection, company_id)
        _imported_fact(connection, import_id, company_id)
        _custom_line(connection, company_id)
    bad_rows = (
        lambda c: _imported_fact(c, import_id, company_id),  # the same (import, line, period)
        lambda c: _imported_fact(c, import_id, company_id, line_code="cogs", fiscal_period="H1"),
        lambda c: _import(c, company_id, format="pdf"),
        lambda c: _import(c, company_id, scale="trillions"),
        lambda c: _custom_line(c, company_id),  # the same code
        lambda c: _custom_line(c, company_id, code="custom:b", statement="XX"),
        lambda c: _custom_line(c, company_id, code="custom:b", kind="stock"),
        lambda c: _custom_line(c, company_id, code="custom:b", unit="EUR"),
    )
    for bad in bad_rows:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            bad(connection)
    with engine.begin() as connection:
        second = _import(connection, company_id, filename="again.csv", format="csv", scale="units")
        _imported_fact(connection, second, company_id)  # a later vintage of the same cell
        _imported_fact(
            connection, second, company_id, line_code="cost_of_revenue", period_start=None
        )


def test_0007_foreign_keys_cascade_on_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        owner = _company(connection, "AAA")
        other = _company(connection, "BBB")
        first = _import(connection, owner)
        _imported_fact(connection, first, owner)
        _custom_line(connection, owner)
        kept = _import(connection, other)
        _imported_fact(connection, kept, other)

        connection.execute(text("DELETE FROM statement_import WHERE id = :id"), {"id": first})
        assert connection.execute(text("SELECT count(*) FROM imported_fact")).scalar() == 1

        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": other})
        assert connection.execute(text("SELECT count(*) FROM imported_fact")).scalar() == 0
        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": owner})
        for table in sorted(_IMPORT_TABLES):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table


def test_0008_makes_cik_nullable_and_adds_source_and_downgrade_restores_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    columns = {c["name"]: c for c in inspect(engine).get_columns("company")}
    assert columns["cik"]["nullable"] is True
    assert columns["source"]["nullable"] is False
    with engine.begin() as connection:
        sec = _company(connection, "AAA")  # an existing-style row: source defaults to 'sec'
        assert (
            connection.execute(
                text("SELECT source FROM company WHERE id = :id"), {"id": sec}
            ).scalar()
            == "sec"
        )
        # Several manual companies share a NULL cik; a real cik stays unique.
        for ticker in ("MAN1", "MAN2"):
            _insert(
                connection,
                "company",
                ticker=ticker,
                cik=None,
                name=ticker,
                fiscal_year_end_month=12,
                currency="USD",
                source="manual",
            )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert(
            connection,
            "company",
            ticker="DUP",
            cik="cik-AAA",
            name="DUP",
            fiscal_year_end_month=12,
            currency="USD",
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert(
            connection,
            "company",
            ticker="BAD",
            cik=None,
            name="BAD",
            fiscal_year_end_month=12,
            currency="USD",
            source="other",
        )

    # A downgrade cannot give a manual company a CIK: it refuses while one exists.
    with pytest.raises(RuntimeError, match="manual"):
        _run_alembic(tmp_path, monkeypatch, ("downgrade", "0007"))
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM company WHERE source = 'manual'"))
    database_url = _run_alembic(tmp_path, monkeypatch, ("downgrade", "0007"))
    engine = create_engine(database_url)
    columns = {c["name"]: c for c in inspect(engine).get_columns("company")}
    assert columns["cik"]["nullable"] is False
    assert "source" not in columns
    with engine.connect() as connection:
        tickers = connection.execute(text("SELECT ticker FROM company")).scalars().all()
    assert tickers == ["AAA"]


def test_0008_keeps_the_rows_that_reference_company_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rebuilding `company` must not fire the ON DELETE CASCADE of the tables that reference it.
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0007"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        owner = _company(connection, "AAA")
        _import(connection, owner)

    def children() -> int:
        with engine.connect() as connection:
            return int(connection.execute(text("SELECT count(*) FROM statement_import")).scalar())

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert children() == 1
    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0007"))
    assert children() == 1


_FORECAST_TABLES = {"scenario", "driver_value"}


def _scenario(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "name": "Base",
        "is_default": 1,
        "base_id": None,
        "revenue_method": "growth",
        "horizon_years": 5,
        "horizon_quarters": 4,
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "scenario", **row)


def _driver_value(connection: Connection, scenario_id: int, **cols: object) -> int:
    row = {
        "scenario_id": scenario_id,
        "driver_code": "revenue_growth",
        "fiscal_year": 2027,
        "fiscal_period": "FY",
        "kind": "value",
        "value": "0.05",
        "source": "manual",
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "driver_value", **row)


def test_0009_upgrade_creates_the_forecast_tables_and_downgrade_removes_only_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0009"))
    inspector = inspect(create_engine(database_url))
    assert _FORECAST_TABLES <= set(inspector.get_table_names())
    uq = {
        table: {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table)}
        for table in _FORECAST_TABLES
    }
    assert ("company_id", "name") in uq["scenario"]
    assert ("scenario_id", "driver_code", "fiscal_year", "fiscal_period") in uq["driver_value"]
    fks = {
        (fk["referred_table"], tuple(fk["constrained_columns"]), fk["options"].get("ondelete"))
        for table in _FORECAST_TABLES
        for fk in inspector.get_foreign_keys(table)
    }
    assert ("company", ("company_id",), "CASCADE") in fks
    assert ("scenario", ("base_id",), "CASCADE") in fks
    assert ("scenario", ("scenario_id",), "CASCADE") in fks
    value = next(c for c in inspector.get_columns("driver_value") if c["name"] == "value")
    assert (value["type"].precision, value["type"].scale) == (28, 10)

    database_url = _run_alembic(tmp_path, monkeypatch, ("downgrade", "0008"))
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert not _FORECAST_TABLES & tables
    assert {"company", "segment_series", "custom_line"} <= tables


def test_0009_uniques_and_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0009"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        base = _scenario(connection, company_id)
        _driver_value(connection, base)
    child = {"name": "X", "is_default": 0, "base_id": base}
    bad_rows = (
        lambda c: _scenario(c, company_id, is_default=0, base_id=base),  # the same name
        lambda c: _scenario(c, company_id, name="Two"),  # a second Base
        lambda c: _scenario(c, company_id, name="X", is_default=0),  # not Base, no base_id
        lambda c: _scenario(c, company_id, name="X", base_id=base),  # Base with a base_id
        lambda c: _scenario(c, company_id, **child, revenue_method="dcf"),
        lambda c: _scenario(c, company_id, **child, segment_dimension="kpi"),
        lambda c: _scenario(c, company_id, **child, horizon_years=4),
        lambda c: _scenario(c, company_id, **child, horizon_years=11),
        lambda c: _scenario(c, company_id, **child, horizon_quarters=3),
        lambda c: _scenario(c, company_id, **child, horizon_quarters=9),
        lambda c: _driver_value(c, base),  # the same (scenario, driver, year, period)
        lambda c: _driver_value(c, base, fiscal_year=2028, fiscal_period="Q1"),
        lambda c: _driver_value(c, base, fiscal_year=2028, kind="delta"),
        lambda c: _driver_value(c, base, fiscal_year=2028, source="user"),
    )
    for bad in bad_rows:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            bad(connection)
    with engine.begin() as connection:
        bull = _scenario(
            connection,
            company_id,
            name="Bull",
            is_default=0,
            base_id=base,
            revenue_method="segments",
            segment_dimension="geo",
            horizon_years=10,
            horizon_quarters=8,
        )
        _driver_value(connection, bull, kind="offset", value="0.03")
        _driver_value(connection, bull, fiscal_year=2028, source="engine", engine_code="arima")
        _scenario(
            connection,
            company_id,
            name="Volume",
            is_default=0,
            base_id=base,
            revenue_method="volume_price",
            volume_kpi="units",
            price_kpi="asp",
        )
        other = _company(connection, "BBB")
        _scenario(connection, other)  # another company has its own Base


def test_0009_foreign_keys_cascade_on_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0009"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        owner = _company(connection, "AAA")
        base = _scenario(connection, owner)
        bull = _scenario(connection, owner, name="Bull", is_default=0, base_id=base)
        _driver_value(connection, base)
        _driver_value(connection, bull)
        other = _company(connection, "BBB")
        _driver_value(connection, _scenario(connection, other))

        def count(table: str) -> int:
            return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar())

        connection.execute(text("DELETE FROM scenario WHERE id = :id"), {"id": bull})
        assert (count("scenario"), count("driver_value")) == (2, 2)
        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": owner})
        assert (count("scenario"), count("driver_value")) == (1, 1)


def test_0009_keeps_existing_rows_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0008"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        owner = _company(connection, "AAA")
        _import(connection, owner)
        _series(connection, owner)

    def counts() -> tuple[int, ...]:
        with engine.connect() as connection:
            return tuple(
                int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar())
                for table in ("company", "statement_import", "segment_series")
            )

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert counts() == (1, 1, 1)
    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0008"))
    assert counts() == (1, 1, 1)


# M4 (user, 2026-10-31): the horizon is fixed at 5 years and 8 quarters, so 0010 drops the columns.
_HORIZON_COLUMNS = {"horizon_years", "horizon_quarters"}


def _scenario_columns(database_url: str) -> set[str]:
    return {c["name"] for c in inspect(create_engine(database_url)).get_columns("scenario")}


def test_0010_drops_the_horizon_columns_and_keeps_every_scenario_and_driver_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0009"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        owner = _company(connection, "AAA")
        base = _scenario(connection, owner, horizon_years=7, horizon_quarters=6)
        bull = _scenario(connection, owner, name="Bull", is_default=0, base_id=base)
        _driver_value(connection, base)
        _driver_value(connection, bull, kind="offset", value="0.03")

    def counts() -> list[int]:
        with engine.connect() as connection:
            return [
                int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar())
                for table in ("scenario", "driver_value")
            ]

    # The app's engine turns foreign keys on: a rebuild of `scenario` must not cascade (G34).
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    assert not _HORIZON_COLUMNS & _scenario_columns(database_url)
    assert counts() == [2, 2]

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0009"))
    assert _HORIZON_COLUMNS <= _scenario_columns(database_url)
    assert counts() == [2, 2]
    with engine.connect() as connection:
        horizons = connection.execute(
            text("SELECT DISTINCT horizon_years, horizon_quarters FROM scenario")
        ).all()
    assert horizons == [(5, 8)]  # the fixed horizon


def test_0010_keeps_the_scenario_keys_and_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    inspector = inspect(create_engine(database_url))
    fks = {
        (fk["referred_table"], tuple(fk["constrained_columns"]), fk["options"].get("ondelete"))
        for fk in inspector.get_foreign_keys("scenario")
    }
    assert fks == {("company", ("company_id",), "CASCADE"), ("scenario", ("base_id",), "CASCADE")}
    assert ("company_id", "name") in {
        tuple(c["column_names"]) for c in inspector.get_unique_constraints("scenario")
    }
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        row = dict(_SCENARIO_NOW)
        base = _insert(connection, "scenario", company_id=company_id, **row)
    for bad in (
        {"name": "Two"},  # a second Base
        {"name": "X", "is_default": 0},  # not Base, no base_id
        {"name": "X", "is_default": 0, "base_id": base, "revenue_method": "dcf"},
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert(connection, "scenario", company_id=company_id, **{**row, **bad})


_SCENARIO_NOW = {
    "name": "Base",
    "is_default": 1,
    "base_id": None,
    "revenue_method": "growth",
    "created_at": _NOW,
    "updated_at": _NOW,
}


# M4 S6b (user, 2026-10-31): a scenario holds exactly three cases; 0011 moves the flat
# Base/Bull/Bear scenarios into one scenario "Main" with cases (docs/erd/forecasting.md
# "Scenarios and cases").


def _old_scenario(connection: Connection, company_id: int, **cols: object) -> int:
    return _insert(connection, "scenario", company_id=company_id, **{**_SCENARIO_NOW, **cols})


def _old_driver(connection: Connection, scenario_id: int, **cols: object) -> int:
    return _driver_value(connection, scenario_id, **cols)


def _flat_company(connection: Connection, ticker: str) -> dict[str, int]:
    """A company holding the flat defaults and one user scenario, as the dev DB held them."""
    owner = _company(connection, ticker)
    base = _old_scenario(connection, owner, revenue_method="segments", segment_dimension="geo")
    bull = _old_scenario(
        connection, owner, name="Bull", is_default=0, base_id=base, revenue_method="growth"
    )
    bear = _old_scenario(connection, owner, name="Bear", is_default=0, base_id=base)
    mine = _old_scenario(connection, owner, name="Mine", is_default=0, base_id=base)
    _old_driver(connection, base, driver_code="gross_margin", value="0.4")
    _old_driver(connection, bull, kind="offset", value="0.03")
    _old_driver(connection, bull, driver_code="gross_margin", kind="offset", value="0.01")
    _old_driver(connection, bear, kind="offset", value="-0.03")
    _old_driver(connection, mine, driver_code="tax_rate", value="0.2")
    _old_driver(connection, mine, kind="offset", value="0.05")  # an offset on the old Base
    return {"owner": owner, "base": base, "bull": bull, "bear": bear, "mine": mine}


def _new_state(database_url: str) -> dict[str, object]:
    """The scenarios (name -> settings), their cases, and every driver row by
    (scenario name, case, code, year) -> (kind, value)."""
    with create_engine(database_url).connect() as connection:
        scenarios = {
            (r.company, r.name): (r.is_default, r.revenue_method, r.segment_dimension)
            for r in connection.execute(
                text(
                    "SELECT c.ticker AS company, s.name, s.is_default, s.revenue_method,"
                    " s.segment_dimension FROM scenario s JOIN company c ON c.id = s.company_id"
                )
            )
        }
        cases = sorted(
            (r.company, r.name, r.case_name)
            for r in connection.execute(
                text(
                    'SELECT c.ticker AS company, s.name, k."case" AS case_name'
                    " FROM scenario_case k JOIN scenario s ON s.id = k.scenario_id"
                    " JOIN company c ON c.id = s.company_id"
                )
            )
        )
        rows = {
            (r.company, r.name, r.case_name, r.driver_code, r.fiscal_year): (
                r.kind,
                round(float(r.value), 6),
            )
            for r in connection.execute(
                text(
                    'SELECT c.ticker AS company, s.name, k."case" AS case_name, d.driver_code,'
                    " d.fiscal_year, d.kind, d.value FROM driver_value d"
                    " JOIN scenario_case k ON k.id = d.case_id"
                    " JOIN scenario s ON s.id = k.scenario_id"
                    " JOIN company c ON c.id = s.company_id"
                )
            )
        }
    return {"scenarios": scenarios, "cases": cases, "rows": rows}


def _all_cases(company: str, *names: str) -> list[tuple[str, str, str]]:
    return [(company, n, c) for n in names for c in ("base", "bear", "bull")]


def test_0011_moves_the_flat_scenarios_into_main_with_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    with create_engine(database_url).begin() as connection:
        _flat_company(connection, "AAA")

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))
    state = _new_state(database_url)

    assert state["scenarios"] == {
        ("AAA", "Main"): (1, "segments", "geo"),  # old Base's settings stay; Bull/Bear's drop
        ("AAA", "Mine"): (0, "growth", None),
    }
    assert state["cases"] == _all_cases("AAA", "Main", "Mine")
    assert state["rows"] == {
        ("AAA", "Main", "base", "gross_margin", 2027): ("value", 0.4),
        ("AAA", "Main", "bull", "revenue_growth", 2027): ("offset", 0.03),
        ("AAA", "Main", "bull", "gross_margin", 2027): ("offset", 0.01),
        ("AAA", "Main", "bear", "revenue_growth", 2027): ("offset", -0.03),
        # Mine's value rows go to its base; its offset (on the old Base) is dropped
        ("AAA", "Mine", "base", "tax_rate", 2027): ("value", 0.2),
    }


def test_0011_downgrade_restores_the_flat_scenarios_and_up_again_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    with create_engine(database_url).begin() as connection:
        _flat_company(connection, "AAA")
        _flat_company(connection, "BBB")
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))
    with create_engine(database_url).begin() as connection:
        # a row on Mine's bull case, added in the new model
        bull = connection.execute(
            text(
                "SELECT k.id FROM scenario_case k JOIN scenario s ON s.id = k.scenario_id"
                " JOIN company c ON c.id = s.company_id"
                " WHERE c.ticker = 'AAA' AND s.name = 'Mine' AND k.\"case\" = 'bull'"
            )
        ).scalar_one()
        _insert(
            connection,
            "driver_value",
            case_id=bull,
            driver_code="gross_margin",
            fiscal_year=2027,
            fiscal_period="FY",
            kind="offset",
            value="0.02",
            source="manual",
            created_at=_NOW,
            updated_at=_NOW,
        )
    up_state = _new_state(database_url)

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0010"))
    with create_engine(database_url).connect() as connection:
        flat = {
            (r.ticker, r.name): (r.is_default, r.parent, r.revenue_method)
            for r in connection.execute(
                text(
                    "SELECT c.ticker, s.name, s.is_default, p.name AS parent, s.revenue_method"
                    " FROM scenario s JOIN company c ON c.id = s.company_id"
                    " LEFT JOIN scenario p ON p.id = s.base_id"
                )
            )
        }
        rows = sorted(
            (r.ticker, r.name, r.driver_code, r.kind, round(float(r.value), 6))
            for r in connection.execute(
                text(
                    "SELECT c.ticker, s.name, d.driver_code, d.kind, d.value FROM driver_value d"
                    " JOIN scenario s ON s.id = d.scenario_id"
                    " JOIN company c ON c.id = s.company_id WHERE c.ticker = 'AAA'"
                )
            )
        )
    for ticker in ("AAA", "BBB"):
        assert flat[(ticker, "Base")] == (1, None, "segments")  # the default is "Base" again
        assert flat[(ticker, "Bull")] == (0, "Base", "segments")  # the scenario's settings
        assert flat[(ticker, "Bear")] == (0, "Base", "segments")
        assert flat[(ticker, "Mine")] == (0, "Base", "growth")
    assert flat[("AAA", "Mine Bull")] == (0, "Base", "growth")  # lossy: on the default Base
    assert ("AAA", "Mine Bear") not in flat  # an empty case is not worth a scenario
    assert rows == sorted(
        [
            ("AAA", "Base", "gross_margin", "value", 0.4),
            ("AAA", "Bull", "revenue_growth", "offset", 0.03),
            ("AAA", "Bull", "gross_margin", "offset", 0.01),
            ("AAA", "Bear", "revenue_growth", "offset", -0.03),
            ("AAA", "Mine", "tax_rate", "value", 0.2),
            ("AAA", "Mine Bull", "gross_margin", "offset", 0.02),
        ]
    )

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))
    again = _new_state(database_url)
    assert again["scenarios"] == {  # "Mine Bull" is its own scenario now, with no rows to keep
        **up_state["scenarios"],  # type: ignore[dict-item]  # a dict in both
        ("AAA", "Mine Bull"): (0, "growth", None),
    }
    lost = ("AAA", "Mine", "bull", "gross_margin", 2027)  # the offset on Mine's own Base
    assert again["rows"] == {k: v for k, v in up_state["rows"].items() if k != lost}  # type: ignore[attr-defined]


def test_0011_keeps_every_row_with_foreign_keys_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rebuilding `scenario` and `driver_value` must not cascade (G34)."""
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _flat_company(connection, "AAA")
        company = _company(connection, "BBB")
        _driver_value(connection, _old_scenario(connection, company))

    def counts() -> dict[str, int]:
        with engine.connect() as connection:
            return {
                t: int(connection.execute(text(f"SELECT count(*) FROM {t}")).scalar())
                for t in ("company", "scenario", "driver_value")
            }

    before = counts()
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))
    after = counts()
    assert after["company"] == before["company"]
    assert after["scenario"] == 3  # AAA: Main + Mine, BBB: Main
    assert after["driver_value"] == before["driver_value"] - 1  # Mine's offset on the old Base
    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0010"))
    assert counts()["company"] == before["company"]
    assert counts()["driver_value"] == before["driver_value"] - 1


def test_0011_renames_the_default_to_a_free_name_when_main_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    with create_engine(database_url).begin() as connection:
        owner = _company(connection, "AAA")
        base = _old_scenario(connection, owner)
        _old_scenario(connection, owner, name="Main", is_default=0, base_id=base)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))

    assert set(_new_state(database_url)["scenarios"]) == {  # type: ignore[call-overload]
        ("AAA", "Main"),
        ("AAA", "Main 2"),
    }


def test_0011_with_no_bull_or_bear_still_gives_the_default_its_three_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0010"))
    with create_engine(database_url).begin() as connection:
        owner = _company(connection, "AAA")
        _old_driver(connection, _old_scenario(connection, owner))
        _company(connection, "BBB")  # no scenario at all: nothing to move

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))
    state = _new_state(database_url)

    assert state["cases"] == _all_cases("AAA", "Main")
    assert list(state["rows"]) == [("AAA", "Main", "base", "revenue_growth", 2027)]  # type: ignore[call-overload]


def _case(connection: Connection, scenario_id: int, case: str) -> int:
    """A `scenario_case` row (`case` is an SQL keyword, so `_insert` cannot write it)."""
    result = connection.execute(
        text(
            'INSERT INTO scenario_case (scenario_id, "case", created_at, updated_at)'
            " VALUES (:scenario_id, :case, :now, :now)"
        ),
        {"scenario_id": scenario_id, "case": case, "now": _NOW},
    )
    return int(result.lastrowid)


def _scenario11(connection: Connection, company_id: int, **cols: object) -> int:
    """A scenario as 0011 has it: no `base_id`."""
    row = {k: v for k, v in _SCENARIO_NOW.items() if k != "base_id"}
    return _insert(connection, "scenario", company_id=company_id, **{**row, **cols})


def test_0011_keys_and_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    inspector = inspect(create_engine(database_url))
    assert "base_id" not in {c["name"] for c in inspector.get_columns("scenario")}
    assert "scenario_id" not in {c["name"] for c in inspector.get_columns("driver_value")}

    def fks(table: str) -> set[tuple[str, tuple[str, ...], str | None]]:
        return {
            (fk["referred_table"], tuple(fk["constrained_columns"]), fk["options"].get("ondelete"))
            for fk in inspector.get_foreign_keys(table)
        }

    assert fks("scenario") == {("company", ("company_id",), "CASCADE")}
    assert fks("scenario_case") == {("scenario", ("scenario_id",), "CASCADE")}
    assert fks("driver_value") == {("scenario_case", ("case_id",), "CASCADE")}
    assert ("scenario_id", "case") in {
        tuple(c["column_names"]) for c in inspector.get_unique_constraints("scenario_case")
    }
    assert ("case_id", "driver_code", "fiscal_year", "fiscal_period") in {
        tuple(c["column_names"]) for c in inspector.get_unique_constraints("driver_value")
    }

    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        main = _scenario11(connection, company_id, name="Main")
        _case(connection, main, "base")
    for bad in (
        lambda c: _scenario11(c, company_id, name="Two"),  # a second default
        lambda c: _scenario11(c, company_id, name="Main", is_default=0),  # the same name
        lambda c: _scenario11(c, company_id, name="X", is_default=0, revenue_method="dcf"),
        lambda c: _case(c, main, "base"),  # the same case twice
        lambda c: _case(c, main, "best"),
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            bad(connection)


def test_0011_cases_and_driver_rows_cascade_on_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        owner = _company(connection, "AAA")
        extra = _scenario11(connection, owner, name="Extra", is_default=0)
        main = _scenario11(connection, owner, name="Main")
        for scenario in (main, extra):
            for case in ("base", "bull"):
                case_id = _case(connection, scenario, case)
                _insert(
                    connection,
                    "driver_value",
                    case_id=case_id,
                    driver_code="gross_margin",
                    fiscal_year=2027,
                    fiscal_period="FY",
                    kind="value",
                    value="0.4",
                    source="manual",
                    created_at=_NOW,
                    updated_at=_NOW,
                )

        def count(table: str) -> int:
            return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar())

        connection.execute(text("DELETE FROM scenario WHERE id = :id"), {"id": extra})
        assert (count("scenario"), count("scenario_case"), count("driver_value")) == (1, 2, 2)
        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": owner})
        assert (count("scenario"), count("scenario_case"), count("driver_value")) == (0, 0, 0)


def test_0011_downgrade_keeps_the_default_s_bull_and_bear_names_when_a_user_scenario_has_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user scenario named "Bull" must not be mistaken for Main's bull case on the way back up."""
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0011"))
    with create_engine(database_url).begin() as connection:
        owner = _company(connection, "AAA")
        main = _scenario11(connection, owner, name="Main")
        mine = _scenario11(connection, owner, name="Bull", is_default=0)
        main_bull = _case(connection, main, "bull")
        for scenario in (main, mine):
            _case(connection, scenario, "base")
        _case(connection, main, "bear")
        _case(connection, mine, "bull")
        _case(connection, mine, "bear")
        _insert(
            connection,
            "driver_value",
            case_id=main_bull,
            driver_code="revenue_growth",
            fiscal_year=2027,
            fiscal_period="FY",
            kind="offset",
            value="0.03",
            source="manual",
            created_at=_NOW,
            updated_at=_NOW,
        )
    before = _new_state(database_url)["rows"]

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0010"), ("upgrade", "0011"))

    after = _new_state(database_url)
    assert after["rows"] == before  # Main's bull offsets are still Main's
    assert ("AAA", "Main") in after["scenarios"]  # type: ignore[operator]


def _driver_row12(connection: Connection, case_id: int, **cols: object) -> int:
    row = {
        "case_id": case_id,
        "driver_code": "gross_margin",
        "fiscal_year": 2027,
        "fiscal_period": "FY",
        "kind": "value",
        "value": "0.4",
        "source": "manual",
        "created_at": _NOW,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "driver_value", **row)


def _scenario_with_case(connection: Connection, ticker: str) -> int:
    owner = _company(connection, ticker)
    main = _scenario11(connection, owner, name="Main")
    return _case(connection, main, "bull")


def test_0012_allows_quarter_rows_and_still_rejects_other_periods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        case_id = _scenario_with_case(connection, "AAA")
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            _driver_row12(connection, case_id, fiscal_period=quarter)
    for bad in (
        lambda c: _driver_row12(c, case_id, fiscal_period="Q5"),
        lambda c: _driver_row12(c, case_id, fiscal_period="TTM"),
        lambda c: _driver_row12(c, case_id, fiscal_period="Q1"),  # the same key twice
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            bad(connection)


def test_0012_downgrade_deletes_the_quarter_rows_and_keeps_the_year_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        case_id = _scenario_with_case(connection, "AAA")
        _driver_row12(connection, case_id, fiscal_year=2027)
        _driver_row12(connection, case_id, fiscal_year=2028)
        _driver_row12(connection, case_id, fiscal_year=2027, fiscal_period="Q1")
        _driver_row12(connection, case_id, fiscal_year=2027, fiscal_period="Q3")

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0011"))
    with engine.begin() as connection:
        kept = connection.execute(
            text("SELECT fiscal_year, fiscal_period FROM driver_value ORDER BY fiscal_year")
        ).all()
        assert [tuple(r) for r in kept] == [(2027, "FY"), (2028, "FY")]
        with pytest.raises(IntegrityError):  # the FY-only check is back
            _driver_row12(connection, case_id, fiscal_period="Q1")


def test_0012_up_again_after_the_downgrade_keeps_the_year_rows_and_the_cascade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        case_id = _scenario_with_case(connection, "AAA")
        _driver_row12(connection, case_id)
    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0011"), ("upgrade", "head"))
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        _driver_row12(connection, case_id, fiscal_period="Q2")
        assert connection.execute(text("SELECT count(*) FROM driver_value")).scalar() == 2
        connection.execute(text("DELETE FROM scenario_case WHERE id = :id"), {"id": case_id})
        assert connection.execute(text("SELECT count(*) FROM driver_value")).scalar() == 0


def _modes(connection: Connection) -> list[tuple[int, int, str]]:
    rows = connection.execute(
        text(
            "SELECT scenario_id, fiscal_year, mode FROM scenario_year_mode"
            " ORDER BY scenario_id, fiscal_year"
        )
    )
    return [tuple(r) for r in rows]  # type: ignore[misc]


def test_0013_creates_the_year_mode_table_with_its_constraints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        owner = _company(connection, "AAA")
        main = _scenario11(connection, owner, name="Main")
        _insert(connection, "scenario_year_mode", scenario_id=main, fiscal_year=2027, mode="annual")
        _insert(
            connection, "scenario_year_mode", scenario_id=main, fiscal_year=2028, mode="quarterly"
        )
    for bad in (
        dict(scenario_id=main, fiscal_year=2027, mode="quarterly"),  # the same year twice
        dict(scenario_id=main, fiscal_year=2029, mode="weekly"),  # not a mode
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert(connection, "scenario_year_mode", **bad)


def test_0013_modes_go_with_their_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with create_engine(database_url).begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        owner = _company(connection, "AAA")
        main = _scenario11(connection, owner, name="Main")
        _insert(
            connection, "scenario_year_mode", scenario_id=main, fiscal_year=2027, mode="quarterly"
        )
        connection.execute(text("DELETE FROM scenario WHERE id = :id"), {"id": main})
        assert _modes(connection) == []


def test_0013_backfills_the_years_that_have_a_quarter_row_in_any_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0012"))
    with create_engine(database_url).begin() as connection:
        owner = _company(connection, "AAA")
        main = _scenario11(connection, owner, name="Main")
        other = _scenario11(connection, owner, name="Other", is_default=0)
        main_base, main_bull = _case(connection, main, "base"), _case(connection, main, "bull")
        other_base = _case(connection, other, "base")
        _driver_row12(connection, main_bull, fiscal_year=2027, fiscal_period="Q1")
        _driver_row12(connection, main_base, fiscal_year=2028, fiscal_period="Q4")
        _driver_row12(connection, main_base, fiscal_year=2028, fiscal_period="Q3")
        _driver_row12(connection, main_base, fiscal_year=2029)  # a year row is not a quarter row
        _driver_row12(connection, other_base, fiscal_year=2029)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))

    with create_engine(database_url).begin() as connection:
        assert _modes(connection) == [(main, 2027, "quarterly"), (main, 2028, "quarterly")]


def test_0013_downgrade_drops_the_table_and_keeps_the_driver_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        case_id = _scenario_with_case(connection, "AAA")
        _driver_row12(connection, case_id, fiscal_period="Q1")
        scenario_id = connection.execute(text("SELECT id FROM scenario")).scalar()
        _insert(
            connection,
            "scenario_year_mode",
            scenario_id=scenario_id,
            fiscal_year=2027,
            mode="quarterly",
        )

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0012"))

    assert "scenario_year_mode" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM driver_value")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM company")).scalar() == 1


def _valuation_row(connection: Connection, case_id: int, **cols: object) -> int:
    row = {"case_id": case_id, "code": "beta", "value": "1.2", "updated_at": _NOW, **cols}
    return _insert(connection, "valuation_input", **row)


def test_0014_creates_the_valuation_input_table_with_its_unique_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        case_id = _scenario_with_case(connection, "AAA")
        _valuation_row(connection, case_id)
        _valuation_row(connection, case_id, code="beta2")
    for bad in (
        dict(code="beta"),  # the same code twice in a case
        dict(code=None),  # NOT NULL
        dict(case_id=999_999),  # no such case
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            _valuation_row(connection, **{"case_id": case_id, **bad})


def test_0014_inputs_go_with_their_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with create_engine(database_url).begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        case_id = _scenario_with_case(connection, "AAA")
        _valuation_row(connection, case_id)
        connection.execute(text("DELETE FROM scenario"))
        assert connection.execute(text("SELECT count(*) FROM valuation_input")).scalar() == 0


def test_0014_downgrade_drops_the_table_and_up_again_recreates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _valuation_row(connection, _scenario_with_case(connection, "AAA"))

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0013"))
    assert "valuation_input" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM scenario_case")).scalar() == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert "valuation_input" in inspect(engine).get_table_names()


def _engine_row(connection: Connection, scenario_id: int, **cols: object) -> int:
    row = {
        "scenario_id": scenario_id,
        "driver_code": "gross_margin",
        "engine_code": "ets",
        "config_json": None,
        "updated_at": _NOW,
        **cols,
    }
    return _insert(connection, "driver_engine_choice", **row)


def _scenario_id(connection: Connection) -> int:
    return int(connection.execute(text("SELECT id FROM scenario")).scalar_one())


def test_0015_creates_the_engine_choice_table_with_its_unique_key_and_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _scenario_with_case(connection, "AAA")
        scenario_id = _scenario_id(connection)
        for code in ("mean", "arima", "ets", "blend", "stl"):
            _engine_row(connection, scenario_id, driver_code=f"d_{code}", engine_code=code)
    for bad in (
        dict(driver_code="d_ets"),  # the same driver twice in a scenario
        dict(driver_code="x", engine_code="auto"),  # `auto` is a missing row, never stored
        dict(driver_code="x", engine_code="prophet"),  # not an engine
        dict(driver_code=None),  # NOT NULL
        dict(driver_code="x", scenario_id=999_999),  # no such scenario
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            _engine_row(connection, **{"scenario_id": scenario_id, **bad})  # type: ignore[arg-type]


def test_0015_choices_go_with_their_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with create_engine(database_url).begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        _scenario_with_case(connection, "AAA")
        _engine_row(connection, _scenario_id(connection))
        connection.execute(text("DELETE FROM scenario"))
        assert connection.execute(text("SELECT count(*) FROM driver_engine_choice")).scalar() == 0


def test_0015_downgrade_drops_the_table_and_up_again_recreates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _scenario_with_case(connection, "AAA")
        _engine_row(connection, _scenario_id(connection))

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0014"))
    assert "driver_engine_choice" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM scenario")).scalar() == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert "driver_engine_choice" in inspect(engine).get_table_names()


def _macro_series(connection: Connection, series_id: str = "DGS10") -> None:
    connection.execute(
        text(
            "INSERT INTO macro_series (series_id, title, frequency, source, fetched_at) "
            "VALUES (:id, 'T', 'daily', 'fred', '2026-11-07 12:00:00')"
        ),
        {"id": series_id},
    )


def _macro_observation(
    connection: Connection, series_id: str = "DGS10", day: str = "2026-11-06"
) -> None:
    connection.execute(
        text("INSERT INTO macro_observation (series_id, date, value) VALUES (:id, :day, 4.2)"),
        {"id": series_id, "day": day},
    )


def test_0016_creates_the_macro_tables_with_their_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _macro_series(connection)
        _macro_observation(connection)
    for bad in (
        lambda c: _macro_series(c),  # the same series twice
        lambda c: _macro_observation(c),  # the same date twice
        lambda c: _macro_observation(c, series_id="NOPE"),  # no such series
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            bad(connection)


def test_0016_observations_go_with_their_series_and_downgrade_drops_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        _macro_series(connection)
        _macro_observation(connection)
        connection.execute(text("DELETE FROM macro_series"))
        assert connection.execute(text("SELECT count(*) FROM macro_observation")).scalar() == 0

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0015"))
    names = inspect(engine).get_table_names()
    assert "macro_series" not in names and "macro_observation" not in names
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert "macro_observation" in inspect(engine).get_table_names()


def _consensus(connection: Connection, company_id: int, period: str = "0y") -> None:
    connection.execute(
        text(
            "INSERT INTO consensus_estimate (company_id, period, metric, low, avg, high, analysts,"
            " year_ago_revenue, fetched_at) VALUES (:company, :period, 'revenue', 1, 2, 3, 4, 5,"
            " '2026-11-07 12:00:00')"
        ),
        {"company": company_id, "period": period},
    )


def test_0017_creates_the_consensus_table_and_downgrade_drops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        owner = _company(connection, "AAA")
        other = _company(connection, "BBB")
        _consensus(connection, owner)
        _consensus(connection, owner, period="+1y")
        _consensus(connection, other)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _consensus(connection, owner)  # the same (company, period, metric) twice
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": owner})
        assert connection.execute(text("SELECT count(*) FROM consensus_estimate")).scalar() == 1

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0016"))
    assert "consensus_estimate" not in inspect(engine).get_table_names()
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert "consensus_estimate" in inspect(engine).get_table_names()


def _guidance_row(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "metric": "revenue",
        "fiscal_year": 2026,
        "fiscal_period": "FY",
        "low": 1,
        "high": 2,
        "basis": "reported",
        "direction": "higher",
        "given_on": "2026-11-07",
        "created_at": "2026-11-07 12:00:00",
        "updated_at": "2026-11-07 12:00:00",
        **cols,
    }
    return _insert(connection, "guidance", **row)


def test_0018_tags_existing_guidance_as_management_and_checks_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0017"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        owner = _company(connection, "AAA")
        _guidance_row(connection, owner)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with engine.begin() as connection:
        assert connection.execute(text("SELECT source FROM guidance")).scalars().all() == [
            "management"
        ]
        _guidance_row(connection, owner, source="consensus")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _guidance_row(connection, owner, source="rumour")

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0017"))
    columns = {c["name"] for c in inspect(engine).get_columns("guidance")}
    assert "source" not in columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM guidance")).scalar() == 2


_ACCOUNTABILITY_TABLES = {
    "forecast_snapshot",
    "forecast_run",
    "forecast_value",
    "valuation_run",
    "audit_log",
}


def _snapshot(connection: Connection, company_id: int, scenario_id: int | None) -> int:
    return _insert(
        connection,
        "forecast_snapshot",
        company_id=company_id,
        scenario_id=scenario_id,
        scenario_name="Main",
        created_at=_NOW,
    )


def _stored_run(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "kind": "backtest",
        "method": "auto",
        "as_of_date": "2024-11-01",
        "created_at": _NOW,
        "engines_json": "{}",
        **cols,
    }
    names = ", ".join(f'"{k}"' for k in row)  # `case` is a keyword
    marks = ", ".join(f":{k}" for k in row)
    result = connection.execute(text(f"INSERT INTO forecast_run ({names}) VALUES ({marks})"), row)
    return int(result.lastrowid)


def _stored_value(connection: Connection, run_id: int, **cols: object) -> None:
    row = {
        "forecast_run_id": run_id,
        "kind": "line",
        "code": "revenue",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "horizon": 1,
        "point": "1.5",
        **cols,
    }
    _insert(connection, "forecast_value", **row)


def _valuation(connection: Connection, run_id: int, **cols: object) -> None:
    row = {
        "forecast_run_id": run_id,
        "method_code": "dcf",
        "label": "DCF",
        "inputs_json": "{}",
        **cols,
    }
    _insert(connection, "valuation_run", **row)


def _audit(connection: Connection, company_id: int) -> None:
    _insert(
        connection,
        "audit_log",
        company_id=company_id,
        entity="driver",
        entity_id=1,
        field="gross_margin|2027|FY",
        label="Gross margin FY27",
        action="edit",
        changed_at=_NOW,
    )


def _seed_accountability(connection: Connection) -> tuple[int, int]:
    """A company with a scenario, a snapshot with a run, a value and a valuation, and an audit
    row; returns (company id, scenario id)."""
    _scenario_with_case(connection, "AAA")
    company_id = int(connection.execute(text("SELECT id FROM company")).scalar_one())
    scenario_id = _scenario_id(connection)
    snapshot_id = _snapshot(connection, company_id, scenario_id)
    run_id = _stored_run(
        connection,
        company_id,
        kind="snapshot",
        method=None,
        snapshot_id=snapshot_id,
        case="base",
    )
    _stored_value(connection, run_id)
    _valuation(connection, run_id)
    _audit(connection, company_id)
    return company_id, scenario_id


def _count(connection: Connection, table: str) -> int:
    return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_0019_creates_the_accountability_tables_with_their_keys_and_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert _ACCOUNTABILITY_TABLES <= set(inspector.get_table_names())
    assert inspector.get_pk_constraint("forecast_value")["constrained_columns"] == [
        "forecast_run_id",
        "kind",
        "code",
        "fiscal_year",
        "fiscal_period",
    ]
    assert ["company_id", "created_at"] in [
        i["column_names"] for i in inspector.get_indexes("forecast_snapshot")
    ]
    assert ["company_id", "id"] in [i["column_names"] for i in inspector.get_indexes("audit_log")]
    assert ["company_id"] in [i["column_names"] for i in inspector.get_indexes("filing")]
    with engine.begin() as connection:
        company_id, _ = _seed_accountability(connection)
        run_id = _stored_run(connection, company_id)
        _stored_value(connection, run_id)
    for table, bad in (
        ("run", dict(kind="live", as_of_date="2020-02-02")),
        ("run", dict(kind="snapshot", case="worst", method=None, as_of_date="2020-01-01")),
        ("run", dict(as_of_date=None)),
        ("run", dict(method=None, as_of_date="2020-03-03")),  # a backtest run names its method
        ("run", dict(kind="snapshot", as_of_date="2020-04-04")),  # a snapshot run names its case
        ("run", dict(company_id=999_999, as_of_date="2020-01-01")),
        ("run", dict(as_of_date="2024-11-01")),  # one run per origin and method
        ("value", dict()),  # the primary key
        ("value", dict(kind="ratio")),
        ("value", dict(code="cash", point=None)),
        ("value", dict(code="cash", forecast_run_id=999_999)),
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            if table == "run":
                _stored_run(connection, **{"company_id": company_id, **bad})  # type: ignore[arg-type]
            else:
                _stored_value(connection, **{"run_id": run_id, **bad})  # type: ignore[arg-type]


def test_0019_a_company_delete_cascades_to_every_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with create_engine(database_url).begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        _seed_accountability(connection)
        assert all(_count(connection, t) == 1 for t in _ACCOUNTABILITY_TABLES)
        connection.execute(text("DELETE FROM company"))
        assert all(_count(connection, t) == 0 for t in _ACCOUNTABILITY_TABLES)


def test_0019_deleting_a_scenario_keeps_the_snapshot_without_its_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with create_engine(database_url).begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        _seed_accountability(connection)
        connection.execute(text("DELETE FROM scenario"))
        kept = connection.execute(
            text("SELECT scenario_id, scenario_name FROM forecast_snapshot")
        ).one()
        assert tuple(kept) == (None, "Main")
        assert _count(connection, "forecast_run") == 1
        assert _count(connection, "forecast_value") == 1


def test_0019_downgrade_drops_only_the_new_tables_and_up_again_recreates_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0019"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_accountability(connection)
    before = set(inspect(engine).get_table_names())

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0018"))
    inspector = inspect(engine)
    assert before - set(inspector.get_table_names()) == _ACCOUNTABILITY_TABLES
    assert ["company_id"] not in [i["column_names"] for i in inspector.get_indexes("filing")]
    with engine.begin() as connection:
        assert _count(connection, "scenario") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert _ACCOUNTABILITY_TABLES <= set(inspect(engine).get_table_names())


def _seed_mapping(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO canonical_item (code, statement, label, kind, unit, sign, display_order)"
            " VALUES ('revenue', 'IS', 'Revenue', 'flow', 'USD', 1, 0)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO concept_mapping (canonical_code, taxonomy, concept, priority)"
            " VALUES ('revenue', 'us-gaap', 'Revenues', 0)"
        )
    )


def test_0020_adds_weight_default_one_and_a_nullable_covers_to_concept_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0019"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_mapping(connection)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    columns = {c["name"]: c for c in inspect(engine).get_columns("concept_mapping")}
    assert columns["weight"]["nullable"] is False
    assert columns["covers"]["nullable"] is True
    with engine.begin() as connection:
        assert tuple(
            connection.execute(text("SELECT weight, covers FROM concept_mapping")).one()
        ) == (1, None)
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO concept_mapping (canonical_code, taxonomy, concept, priority,"
                    " weight) VALUES ('revenue', 'us-gaap', 'Other', 1, NULL)"
                )
            )


def test_0020_downgrade_drops_only_the_two_columns_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_mapping(connection)

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0019"))
    names = {c["name"] for c in inspect(engine).get_columns("concept_mapping")}
    assert names == {"id", "canonical_code", "taxonomy", "concept", "priority", "company_id"}
    with engine.begin() as connection:
        assert _count(connection, "concept_mapping") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    names = {c["name"] for c in inspect(engine).get_columns("concept_mapping")}
    assert {"weight", "covers"} <= names


def _seed_filing_and_fact(connection: Connection) -> tuple[int, int]:
    company_id = _company(connection, "AAA")
    filing_id = _insert(
        connection,
        "filing",
        company_id=company_id,
        accession_no="0000000001-24-000001",
        form="10-K",
        filed_at="2024-11-01",
        period_end="2024-09-28",
    )
    _insert(
        connection,
        "raw_fact",
        company_id=company_id,
        filing_id=filing_id,
        taxonomy="us-gaap",
        concept="Assets",
        unit="USD",
        period_end="2024-09-28",
        value=5,
    )
    return company_id, filing_id


def _line(connection: Connection, filing_id: int, **cols: object) -> int:
    row: dict[str, object] = {
        "filing_id": filing_id,
        "statement": "CF",
        "position": 1,
        "taxonomy": "msft",
        "concept": "DepreciationAmortizationAndOther",
        "label": "Depreciation, amortization, and other",
        "calc_parent_taxonomy": "us-gaap",
        "calc_parent_concept": "NetCashProvidedByUsedInOperatingActivities",
        "calc_weight": 1,
    }
    row.update(cols)
    return _insert(connection, "filing_line", **row)


def test_0021_adds_the_filing_xbrl_columns_and_fact_source_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0020"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_filing_and_fact(connection)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))

    filing_columns = {c["name"]: c for c in inspect(engine).get_columns("filing")}
    assert filing_columns["xbrl_status"]["nullable"] is True
    assert filing_columns["xbrl_parser_version"]["nullable"] is True
    fact_columns = {c["name"]: c for c in inspect(engine).get_columns("raw_fact")}
    assert fact_columns["source"]["nullable"] is False
    with engine.begin() as connection:
        assert tuple(
            connection.execute(text("SELECT xbrl_status, xbrl_parser_version FROM filing")).one()
        ) == (None, None)
        assert connection.execute(text("SELECT source FROM raw_fact")).scalar_one() == (
            "companyfacts"
        )


def test_0021_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _, filing_id = _seed_filing_and_fact(connection)
    bad = [
        "UPDATE filing SET xbrl_status = 'maybe'",
        "UPDATE raw_fact SET source = 'guess'",
        "UPDATE raw_fact SET source = NULL",
    ]
    for statement in bad:
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(text(statement))
    with engine.begin() as connection, pytest.raises(IntegrityError):
        _line(connection, filing_id, statement="EQ")


def test_0021_filing_line_is_unique_per_statement_and_concept_and_cascades_from_filing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _, filing_id = _seed_filing_and_fact(connection)
        _line(connection, filing_id)
        _line(connection, filing_id, statement="IS")  # the same concept on another statement
    with engine.begin() as connection, pytest.raises(IntegrityError):
        _line(connection, filing_id, position=2)

    indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes("filing_line")}
    assert indexes["ix_filing_line_filing_id"] == ["filing_id"]
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("DELETE FROM filing"))
        assert _count(connection, "filing_line") == 0
        assert _count(connection, "raw_fact") == 0


def test_0021_downgrade_drops_only_what_it_added_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _, filing_id = _seed_filing_and_fact(connection)
        _line(connection, filing_id)

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0020"))

    assert "filing_line" not in inspect(engine).get_table_names()
    assert {c["name"] for c in inspect(engine).get_columns("filing")} == {
        "id",
        "company_id",
        "accession_no",
        "form",
        "filed_at",
        "fiscal_year",
        "fiscal_period",
        "period_end",
    }
    assert "source" not in {c["name"] for c in inspect(engine).get_columns("raw_fact")}
    with engine.begin() as connection:
        assert _count(connection, "filing") == 1
        assert _count(connection, "raw_fact") == 1
        assert _count(connection, "company") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert "filing_line" in inspect(engine).get_table_names()


# --- 0022: line classification (M7d S3, docs/erd/face-tree.md "Storage") ---------------------


def _classification(connection: Connection, company_id: int, **cols: object) -> int:
    row: dict[str, object] = {
        "company_id": company_id,
        "statement": "BS",
        "taxonomy": "aapl",
        "concept": "Widgets",
        "classifier": "claude:claude-haiku-5-5",
        "codes": '["inventory"]',
        "confidence": "0.9100",
        "status": "proposed",
        "created_at": _NOW,
    }
    row.update(cols)
    return _insert(connection, "line_classification", **row)


def _classification_run(connection: Connection, company_id: int, **cols: object) -> int:
    row: dict[str, object] = {
        "company_id": company_id,
        "classifier": "claude:claude-haiku-5-5",
        "status": "done",
        "started_at": _NOW,
        "lines_asked": 3,
        "lines_answered": 3,
        "input_tokens": 100,
        "output_tokens": 10,
        "cost_usd": "0.000015",
    }
    row.update(cols)
    return _insert(connection, "classification_run", **row)


def test_0022_adds_the_mode_columns_with_their_defaults_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0021"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        _snapshot(connection, company_id, None)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))

    company_columns = {c["name"]: c for c in inspect(engine).get_columns("company")}
    assert company_columns["classification_mode"]["nullable"] is False
    assert company_columns["classification_source"]["nullable"] is True
    snapshot_columns = {c["name"]: c for c in inspect(engine).get_columns("forecast_snapshot")}
    assert snapshot_columns["classification_mode"]["nullable"] is True
    with engine.begin() as connection:
        assert tuple(
            connection.execute(
                text("SELECT classification_mode, classification_source FROM company")
            ).one()
        ) == ("off", None)
        # a snapshot older than the migration does not know its mode
        assert (
            connection.execute(
                text("SELECT classification_mode FROM forecast_snapshot")
            ).scalar_one()
            is None
        )
        assert _count(connection, "line_classification") == 0
        assert _count(connection, "classification_run") == 0


def test_0022_one_answer_per_classifier_and_line_and_the_checks_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        other_id = _company(connection, "BBB")
        _classification(connection, company_id)
        _classification(connection, company_id, classifier="jev:jev-latest")
        _classification(connection, company_id, classifier="user")
        _classification(connection, company_id, statement="IS")
        _classification(connection, company_id, taxonomy="us-gaap")
        _classification(connection, other_id)
    duplicates_and_bad_values: list[dict[str, object]] = [
        {},  # the same company, line and classifier
        {"concept": "A", "statement": "EQ"},
        {"concept": "B", "status": "maybe"},
        {"concept": "C", "codes": None},
        {"concept": "D", "confidence": None},
        {"concept": "E", "classifier": None},
    ]
    for cols in duplicates_and_bad_values:
        with engine.begin() as connection, pytest.raises(IntegrityError):
            _classification(connection, company_id, **cols)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        _classification_run(connection, company_id, status="paused")

    indexes = {
        i["name"]: i["column_names"] for i in inspect(engine).get_indexes("line_classification")
    }
    assert indexes["ix_line_classification_company_id"] == ["company_id"]


def test_0022_allows_one_running_run_in_the_whole_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        other_id = _company(connection, "BBB")
        for status in ("done", "done", "failed", "failed", "stopped", "stopped"):
            _classification_run(connection, company_id, status=status)
        running = _classification_run(connection, company_id, status="running")
    for owner_id in (company_id, other_id):
        with engine.begin() as connection, pytest.raises(IntegrityError):
            _classification_run(connection, owner_id, status="running")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE classification_run SET status = 'done' WHERE id = :id"), {"id": running}
        )
        _classification_run(connection, other_id, status="running")


def test_0022_rows_go_with_the_company_and_outlive_their_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        company_id = _company(connection, "AAA")
        kept_id = _company(connection, "BBB")
        run_id = _classification_run(connection, kept_id)
        _classification(connection, kept_id, run_id=run_id)
        _classification(connection, company_id, run_id=_classification_run(connection, company_id))

        connection.execute(text("DELETE FROM classification_run WHERE id = :id"), {"id": run_id})
        assert (
            connection.execute(
                text("SELECT run_id FROM line_classification WHERE company_id = :id"),
                {"id": kept_id},
            ).scalar_one()
            is None
        )

        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": company_id})
        assert _count(connection, "line_classification") == 1
        assert _count(connection, "classification_run") == 0


def test_0022_downgrade_drops_only_what_it_added_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0021"))
    engine = create_engine(database_url)
    before = {
        table: {c["name"] for c in inspect(engine).get_columns(table)}
        for table in ("company", "forecast_snapshot")
    }
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        company_id = _company(connection, "AAA")
        _snapshot(connection, company_id, None)
        _audit(connection, company_id)  # a row that cascades from `company` (G34)
        _classification(connection, company_id, run_id=_classification_run(connection, company_id))

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0021"))

    engine.dispose()
    tables = inspect(engine).get_table_names()
    assert "line_classification" not in tables and "classification_run" not in tables
    for table, columns in before.items():
        assert {c["name"] for c in inspect(engine).get_columns(table)} == columns
    with engine.begin() as connection:
        assert _count(connection, "company") == 1
        assert _count(connection, "forecast_snapshot") == 1
        assert _count(connection, "audit_log") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
    assert "line_classification" in inspect(engine).get_table_names()


# --- 0023: pending filings (M7c S1, docs/erd/data.md "New-filing detection") -------------------


def _pending(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "accession_no": f"acc-{company_id}",
        "form": "10-Q",
        "filed_at": "2026-10-30",
        "period_end": "2026-09-26",
        "detected_at": _NOW,
    } | cols
    return _insert(connection, "pending_filing", **row)


def test_0023_adds_the_pending_filing_table_and_the_check_time_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0022"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _company(connection, "AAA")

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0023"))

    engine.dispose()
    inspector = inspect(engine)
    assert "pending_filing" in inspector.get_table_names()
    assert "ix_pending_filing_company_id" in {
        i["name"] for i in inspector.get_indexes("pending_filing")
    }
    with engine.begin() as connection:
        assert connection.execute(text("SELECT filings_checked_at FROM company")).all() == [(None,)]


def test_0023_accession_is_unique_form_is_checked_and_rows_go_with_the_company(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0023"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        kept_id = _company(connection, "BBB")
        _pending(connection, company_id, accession_no="a1", period_end=None)
        _pending(connection, kept_id, accession_no="b1", form="10-K")
    for bad in ({"accession_no": "a1"}, {"accession_no": "a2", "form": "10-K/A"}):
        with engine.begin() as connection, pytest.raises(IntegrityError):
            _pending(connection, company_id, **bad)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        _pending(connection, company_id, accession_no="a3", filed_at=None)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": company_id})
        assert connection.execute(text("SELECT accession_no FROM pending_filing")).all() == [
            ("b1",)
        ]


def test_0023_downgrade_drops_only_what_it_added_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0022"))
    engine = create_engine(database_url)
    before = {c["name"] for c in inspect(engine).get_columns("company")}
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0023"))
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        company_id = _company(connection, "AAA")
        _audit(connection, company_id)  # a row that cascades from `company` (G34)
        _pending(connection, company_id)

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0022"))

    engine.dispose()
    assert "pending_filing" not in inspect(engine).get_table_names()
    assert {c["name"] for c in inspect(engine).get_columns("company")} == before
    with engine.begin() as connection:
        assert _count(connection, "company") == 1
        assert _count(connection, "audit_log") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0023"))
    assert "pending_filing" in inspect(engine).get_table_names()


# --- 0024: snapshot origin (M7c S2, docs/erd/accountability.md "Automatic snapshots") ----------


def test_0024_adds_origin_and_trigger_and_existing_snapshots_are_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0023"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _snapshot(connection, _company(connection, "AAA"), None)

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0024"))

    engine.dispose()
    columns = {c["name"]: c for c in inspect(engine).get_columns("forecast_snapshot")}
    assert columns["origin"]["nullable"] is False
    assert columns["trigger_accession"]["nullable"] is True
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT origin, trigger_accession FROM forecast_snapshot")
        ).all() == [("manual", None)]


def test_0024_origin_is_manual_or_auto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0024"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        _insert(
            connection,
            "forecast_snapshot",
            company_id=company_id,
            scenario_name="Main",
            created_at=_NOW,
            origin="auto",
            trigger_accession="0000320193-26-000020",
        )
    for bad in ("scheduled", None):
        with engine.begin() as connection, pytest.raises(IntegrityError):
            _insert(
                connection,
                "forecast_snapshot",
                company_id=company_id,
                scenario_name="Main",
                created_at=_NOW,
                origin=bad,
            )


def test_0024_downgrade_drops_only_what_it_added_and_keeps_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0023"))
    engine = create_engine(database_url)
    before = {c["name"] for c in inspect(engine).get_columns("forecast_snapshot")}
    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0024"))
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        company_id = _company(connection, "AAA")
        _audit(connection, company_id)  # a row that cascades from `company` (G34)
        _snapshot(connection, company_id, None)

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0023"))

    engine.dispose()
    assert {c["name"] for c in inspect(engine).get_columns("forecast_snapshot")} == before
    with engine.begin() as connection:
        assert _count(connection, "forecast_snapshot") == 1
        assert _count(connection, "audit_log") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0024"))
    assert "origin" in {c["name"] for c in inspect(engine).get_columns("forecast_snapshot")}


# --- 0025: thesis checkpoints (M7c S3, docs/erd/workspace.md "Thesis checkpoints") -------------


def _checkpoint(connection: Connection, company_id: int, **cols: object) -> int:
    row = {
        "company_id": company_id,
        "label": "Margins hold",
        "statement": "gross_margin > 44%",
        "freq": "ttm",
        "margin": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    } | cols
    return _insert(connection, "thesis_checkpoint", **row)


def test_0025_creates_the_checkpoint_table_with_its_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0025"))
    inspector = inspect(create_engine(database_url))
    assert "thesis_checkpoint" in inspector.get_table_names()
    assert "ix_thesis_checkpoint_company_id" in {
        i["name"] for i in inspector.get_indexes("thesis_checkpoint")
    }
    nullable = {c["name"]: c["nullable"] for c in inspector.get_columns("thesis_checkpoint")}
    assert nullable == {
        "id": False,
        "company_id": False,
        "label": False,
        "statement": False,
        "freq": False,
        "margin": True,
        "created_at": False,
        "updated_at": False,
    }


@pytest.mark.parametrize(
    "bad", [{"freq": "quarterly"}, {"margin": -0.01}, {"label": None}, {"statement": None}]
)
def test_0025_checks_hold_at_the_database_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: dict[str, object]
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0025"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        _checkpoint(connection, company_id, freq="annual", margin=0)  # the boundaries pass
    with engine.begin() as connection, pytest.raises(IntegrityError):
        _checkpoint(connection, company_id, **bad)


def test_0025_checkpoints_go_with_their_company(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0025"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        gone = _company(connection, "AAA")
        kept = _company(connection, "BBB")
        _checkpoint(connection, gone)
        _checkpoint(connection, kept, label="kept")
        connection.execute(text("DELETE FROM company WHERE id = :id"), {"id": gone})
        assert connection.execute(text("SELECT label FROM thesis_checkpoint")).all() == [("kept",)]


def test_0025_downgrade_drops_only_the_table_and_up_again_recreates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "0025"))
    engine = create_engine(database_url)
    with engine.begin() as connection:
        company_id = _company(connection, "AAA")
        _audit(connection, company_id)
        _checkpoint(connection, company_id)

    _run_alembic(tmp_path, monkeypatch, ("downgrade", "0024"))

    engine.dispose()
    assert "thesis_checkpoint" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        assert _count(connection, "company") == 1
        assert _count(connection, "audit_log") == 1

    _run_alembic(tmp_path, monkeypatch, ("upgrade", "0025"))
    assert "thesis_checkpoint" in inspect(engine).get_table_names()
