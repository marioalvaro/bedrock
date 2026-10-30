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
    comps_member,
    comps_set,
    concept_mapping,
    corporate_action,
    custom_line,
    driver_value,
    filing,
    guidance,
    imported_fact,
    note,
    off_balance_item,
    price_daily,
    qoe_custom_rule,
    qoe_threshold,
    raw_fact,
    scenario,
    segment_series,
    segment_value,
    statement_import,
)
from bedrock.models.base import Base

# Importing registers every table on Base.metadata, so the drift test below sees them all.
_MODELS = (
    adjustment,
    canonical_item,
    company,
    comps_member,
    comps_set,
    concept_mapping,
    corporate_action,
    custom_line,
    driver_value,
    filing,
    guidance,
    imported_fact,
    note,
    off_balance_item,
    price_daily,
    qoe_custom_rule,
    qoe_threshold,
    raw_fact,
    scenario,
    segment_series,
    segment_value,
    statement_import,
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
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
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
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
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
    database_url = _run_alembic(tmp_path, monkeypatch, ("upgrade", "head"))
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
