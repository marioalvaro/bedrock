"""A manual company filled with AAPL's own prefilled template reads like AAPL (FR-DATA-15).

`AAPLM` has no SEC data at all: everything it shows comes from the import. The values are typed
in units (scale `units`), so the round trip loses nothing."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.services.companies import add_manual_company
from bedrock.services.imports import confirm_import, import_template
from bedrock.services.ratios import ratios
from bedrock.services.refresh import refresh_company
from bedrock.services.statements import build_statements, fiscal_periods, mapping_gaps

from .seed import fake_sources, follow

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


@pytest.fixture
def pair(db_session: Session) -> Iterator[tuple[Company, Company]]:
    sources = fake_sources()
    aapl = follow(db_session, sources.edgar, "AAPL")
    refresh_company(db_session, sources, "AAPL", NOW)
    template = import_template(db_session, aapl, "xlsx", "units", True)
    aaplm = add_manual_company(db_session, "AAPLM", "Apple (manual)", 9, aapl.sic).company
    result = confirm_import(db_session, aaplm, template, "aapl.xlsx", None, NOW)
    assert result.import_id is not None and result.preview.fills
    yield aapl, aaplm


def _cells(session: Session, company: Company) -> dict[tuple[str, str, str], tuple[Any, Any]]:
    """(value, provenance) of every annual and quarterly cell, by (statement, code, period key)."""
    out: dict[tuple[str, str, str], tuple[Any, Any]] = {}
    for statement in ("IS", "BS", "CF"):
        for freq in ("annual", "quarterly"):
            table = build_statements(session, company, statement, freq)  # type: ignore[arg-type]
            for row in table.rows:
                for period, value, provenance in zip(
                    table.periods, row.values, row.provenance, strict=True
                ):
                    out[(statement, row.code, period.key)] = (value, provenance)
    return out


def test_the_manual_company_has_the_calendar_of_aapl(
    db_session: Session, pair: tuple[Company, Company]
) -> None:
    aapl, aaplm = pair

    assert fiscal_periods(db_session, aaplm) == fiscal_periods(db_session, aapl)
    for statement, freq in (("IS", "annual"), ("IS", "quarterly"), ("BS", "quarterly")):
        mine = build_statements(db_session, aaplm, statement, freq)  # type: ignore[arg-type]
        theirs = build_statements(db_session, aapl, statement, freq)  # type: ignore[arg-type]
        assert [(p.key, p.start, p.end) for p in mine.periods] == [
            (p.key, p.start, p.end) for p in theirs.periods
        ]


def test_every_cell_aapl_has_equals_aapls(
    db_session: Session, pair: tuple[Company, Company]
) -> None:
    aapl, aaplm = pair

    theirs, mine = _cells(db_session, aapl), _cells(db_session, aaplm)

    assert mine.keys() == theirs.keys()
    assert sum(v is not None for v, _ in theirs.values()) > 5_000  # not vacuous
    # Where AAPL shows a value, so does AAPLM, the same one (the computed rows included).
    assert {
        k: (theirs[k][0], mine[k][0])
        for k in theirs
        if theirs[k][0] != mine[k][0] and theirs[k][0] is not None
    } == {}
    # A file is one filing, so an identity can solve what AAPL's mixed filings left empty: the
    # cash roll-forward gives an unreported FX effect as 0. Nothing else is added.
    extra = {k: v for k, v in mine.items() if theirs[k][0] is None and v[0] is not None}
    assert extra and {k[1] for k in extra} == {"fx_effect"}
    assert {v for v in extra.values()} == {(0, "derived")}


def test_a_manual_company_shows_imported_and_derived_cells_only(
    db_session: Session, pair: tuple[Company, Company]
) -> None:
    _, aaplm = pair

    mine = _cells(db_session, aaplm)

    assert mine[("IS", "revenue", "FY2024")][1] == "imported"
    assert {p for v, p in mine.values() if v is not None} <= {
        "imported",
        "derived",
        "zero_inferred",
    }


def test_the_balance_sheets_of_the_manual_company_foot(
    db_session: Session, pair: tuple[Company, Company]
) -> None:
    _, aaplm = pair

    for freq in ("annual", "quarterly"):
        table = build_statements(db_session, aaplm, "BS", freq)  # type: ignore[arg-type]
        assert table.balance_check and all(check.ok for check in table.balance_check)


def test_the_ratios_match_apart_from_the_price_based_ones(
    db_session: Session, pair: tuple[Company, Company]
) -> None:
    aapl, aaplm = pair

    for freq in ("annual", "quarterly"):
        theirs = ratios(db_session, aapl, freq, "reported")  # type: ignore[arg-type]
        mine = ratios(db_session, aaplm, freq, "reported")  # type: ignore[arg-type]
        assert [p.key for p in mine.periods] == [p.key for p in theirs.periods]
        for a, b in zip(theirs.rows, mine.rows, strict=True):
            assert a.code == b.code
            if a.category != "Valuation":  # no price history for AAPLM
                assert a.values == b.values, a.code


def test_the_manual_company_has_no_unmapped_concepts(
    db_session: Session, pair: tuple[Company, Company]
) -> None:
    _, aaplm = pair

    assert mapping_gaps(db_session, aaplm).unmapped_concepts == []
