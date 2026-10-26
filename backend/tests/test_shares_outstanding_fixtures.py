"""Shares outstanding over the recorded fixtures (docs/erd/data.md "R7"): Deere tags the period-end
count only from FY2023, so its earlier years and every quarter end come from issued less treasury
and from the cover page."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.services.ratios import ratios
from bedrock.services.refresh import refresh_company
from bedrock.statements.build import Row
from bedrock.statements.cells import solve_cells
from bedrock.statements.periods import fiscal_calendar
from tests.seed import fake_sources, follow
from tests.statements_pipeline import run_pipeline

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)


def row(ticker: str, freq: str, code: str) -> Row:
    table = (run_pipeline(ticker).annual if freq == "annual" else run_pipeline(ticker).quarterly)[
        "BS"
    ]
    return next(r for r in table.rows if r.code == code)


def by_period(ticker: str, freq: str, code: str) -> dict[str, tuple[Decimal | None, str | None]]:
    table = (run_pipeline(ticker).annual if freq == "annual" else run_pipeline(ticker).quarterly)[
        "BS"
    ]
    r = row(ticker, freq, code)
    return {
        p.key: (v, prov) for p, v, prov in zip(table.periods, r.values, r.provenance, strict=True)
    }


def test_deere_years_without_a_reported_count_get_issued_less_treasury() -> None:
    outstanding = by_period("DE", "annual", "shares_outstanding")
    issued = by_period("DE", "annual", "shares_issued")
    treasury = by_period("DE", "annual", "treasury_shares")

    for year in range(2018, 2023):
        value, provenance = outstanding[f"FY{year}"]
        issued_value, _ = issued[f"FY{year}"]
        treasury_value, _ = treasury[f"FY{year}"]
        assert issued_value is not None and treasury_value is not None
        assert (value, provenance) == (issued_value - treasury_value, "derived")


def test_the_identity_agrees_with_the_reported_count_where_both_exist() -> None:
    """The reported count is rounded to 0.1 M shares, so the two agree within that."""
    outstanding = by_period("DE", "annual", "shares_outstanding")
    issued = by_period("DE", "annual", "shares_issued")
    treasury = by_period("DE", "annual", "treasury_shares")
    checked = 0
    for year in (2023, 2024, 2025):
        reported, provenance = outstanding[f"FY{year}"]
        issued_value, _ = issued[f"FY{year}"]
        treasury_value, _ = treasury[f"FY{year}"]
        assert provenance == "reported" and reported is not None
        assert issued_value is not None and treasury_value is not None
        assert abs(issued_value - treasury_value - reported) <= 50_000
        checked += 1

    assert checked == 3


def test_every_deere_quarter_end_has_a_count_and_only_the_cover_page_ones_are_approximated() -> (
    None
):
    quarterly = by_period("DE", "quarterly", "shares_outstanding")
    annual = by_period("DE", "annual", "shares_outstanding")
    latest = max(p for p in quarterly if p.endswith(("Q1", "Q2", "Q3", "Q4")))

    year_ends = {f"{k}Q4": v for k, v in annual.items()}
    assert quarterly[latest][0] is not None
    for key, (value, provenance) in quarterly.items():
        if key.endswith("Q4") and key in year_ends:
            assert (value, provenance) == year_ends[key]  # Q4 is the year-end balance
    recent = [v for k, v in quarterly.items() if k >= "FY2012Q1"]
    assert all(v is not None for v, _ in recent)
    assert {prov for _, prov in recent} <= {"reported", "derived", "approximated"}
    assert any(prov == "approximated" for _, prov in recent)


def test_a_cover_page_cell_names_the_filing_it_came_from() -> None:
    p = run_pipeline("DE")
    cells = solve_cells(p.canonical, p.items, fiscal_calendar(p.canonical), p.rules).cells
    approximated = [
        (key, cell)
        for key, cell in cells.items()
        if key[0] == "shares_outstanding" and cell.provenance == "approximated"
    ]

    assert len(approximated) > 30
    for _, cell in approximated:
        assert cell.source is not None
        assert (cell.source.taxonomy, cell.source.concept) == (
            "dei",
            "EntityCommonStockSharesOutstanding",
        )
        assert cell.derivation is not None
        assert cell.derivation.formula.startswith(
            f"cover-page shares outstanding of {cell.source.form} {cell.source.accession_no}"
        )


@pytest.fixture
def de(db_session: Session) -> Iterator[Company]:
    sources = fake_sources()
    company = follow(db_session, sources.edgar, "DE")
    refresh_company(db_session, sources, "DE", NOW)
    yield company


def test_deere_has_a_ttm_pe_and_the_current_multiples(db_session: Session, de: Company) -> None:
    table = ratios(db_session, de, "ttm", "reported")

    for code in ("pe", "pb", "ps", "p_fcf", "earnings_yield"):
        values = next(r for r in table.rows if r.code == code).values
        assert values[-1] is not None, code
