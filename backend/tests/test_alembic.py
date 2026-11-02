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
