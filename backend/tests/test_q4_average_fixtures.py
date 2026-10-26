"""Q4 shares, Q4 EPS and TTM EPS over the four recorded companyfacts fixtures (docs/erd/data.md
"R2"): the reported Q4 EPS of the earnings releases, and the properties every rebuilt cell has."""

from decimal import Decimal
from functools import cache

import pytest

from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cell_types import Cell, CellKey
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.periods import (
    annual_periods,
    fiscal_calendar,
    quarterly_periods,
    ttm_windows,
)
from tests.statements_pipeline import run_pipeline

TICKERS = ["AAPL", "MSFT", "COST", "DE"]
EPS = ("eps_basic", "eps_diluted")
SHARES = ("shares_basic", "shares_diluted")

# Diluted EPS of the fourth quarter as each company's earnings release states it (Apple, Microsoft,
# Costco and Deere press releases for the quarter ended Sep 2023/2024, Jun 2023/2024, Sep 3 2023 /
# Sep 1 2024 and Oct 2023/2024). The engine rebuilds it from the year and Q1-Q3, within a cent.
REPORTED_Q4_EPS = {
    ("AAPL", "FY2023Q4"): Decimal("1.46"),
    ("AAPL", "FY2024Q4"): Decimal("0.97"),
    ("MSFT", "FY2023Q4"): Decimal("2.69"),
    ("MSFT", "FY2024Q4"): Decimal("2.95"),
    ("COST", "FY2023Q4"): Decimal("4.86"),
    ("COST", "FY2024Q4"): Decimal("5.29"),
    ("DE", "FY2023Q4"): Decimal("8.26"),
    ("DE", "FY2024Q4"): Decimal("4.55"),
}


@cache
def solved(ticker: str) -> SolvedCells:
    p = run_pipeline(ticker)
    return solve_cells(p.canonical, p.items, fiscal_calendar(p.canonical), p.rules)


def table(ticker: str, freq: str) -> StatementTable:
    p = run_pipeline(ticker)
    return (p.annual if freq == "annual" else p.quarterly)["IS"]


@pytest.mark.parametrize(("ticker", "period"), sorted(REPORTED_Q4_EPS))
def test_q4_diluted_eps_matches_the_earnings_release_within_a_cent(
    ticker: str, period: str
) -> None:
    cell = solved(ticker).cells[("eps_diluted", period)]

    assert cell.value is not None
    assert abs(cell.value - REPORTED_Q4_EPS[(ticker, period)]) <= Decimal("0.01")
    assert cell.provenance == "approximated"


@pytest.mark.parametrize("ticker", TICKERS)
def test_no_q4_average_rule_refuses_a_fixture_year(ticker: str) -> None:
    refused = [w for w in solved(ticker).warnings if w.rule in ("q4_shares", "q4_eps")]

    assert refused == []


def approximated(cells: dict[CellKey, Cell]) -> list[CellKey]:
    return [key for key, cell in cells.items() if cell.provenance == "approximated"]


@pytest.mark.parametrize("ticker", TICKERS)
def test_only_q4_of_the_share_and_eps_lines_is_approximated(ticker: str) -> None:
    """The cover-page share counts (R7, `shares_outstanding`) are approximated at any period end."""
    keys = [k for k in approximated(solved(ticker).cells) if k[0] != "shares_outstanding"]

    assert keys
    assert {code for code, _ in keys} <= {*SHARES, *EPS}
    assert all(period.endswith("Q4") for _, period in keys)


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_four_quarters_weighted_by_their_days_give_back_the_year(ticker: str) -> None:
    cells = solved(ticker).cells
    calendar = fiscal_calendar(run_pipeline(ticker).canonical)
    periods = {p.key: p for p in annual_periods(calendar) + quarterly_periods(calendar)}
    checked = 0
    for code in SHARES:
        for year in calendar.years:
            keys = [f"FY{year.fiscal_year}Q{n}" for n in (1, 2, 3, 4)]
            fiscal = cells.get((code, f"FY{year.fiscal_year}"))
            if fiscal is None or fiscal.value is None or not all(k in periods for k in keys):
                continue
            parts = [cells[(code, k)].value for k in keys]
            if any(v is None for v in parts):
                continue
            days = [(periods[k].end - periods[k].start).days + 1 for k in keys]
            mean = sum((v * d for v, d in zip(parts, days, strict=True) if v is not None), 0) / sum(
                days
            )
            assert abs(Decimal(mean) - fiscal.value) <= 1, (code, year.fiscal_year)
            checked += 1

    assert checked >= 10


def line(t: StatementTable, code: str) -> dict[str, tuple[Decimal | None, str | None]]:
    row = next(r for r in t.rows if r.code == code)
    return {
        p.key: (v, prov) for p, v, prov in zip(t.periods, row.values, row.provenance, strict=True)
    }


@pytest.mark.parametrize("ticker", TICKERS)
def test_ttm_eps_is_the_sum_of_its_quarters_and_stays_near_the_year(ticker: str) -> None:
    p = run_pipeline(ticker)
    ttm = build_statement(p.canonical, p.items, "IS", "ttm", rules=p.rules)
    quarterly = table(ticker, "quarterly")
    annual = table(ticker, "annual")
    checked = 0
    for code in EPS:
        per_quarter = {k: v for k, (v, _) in line(quarterly, code).items()}
        per_year = {k: v for k, (v, _) in line(annual, code).items()}
        for window in ttm_windows(fiscal_calendar(p.canonical)):
            value, provenance = line(ttm, code)[window.period.key]
            parts = [per_quarter.get(q.key) for q in window.quarters]
            if any(v is None for v in parts):
                assert value is None
                continue
            assert value == sum((v for v in parts if v is not None), Decimal(0))
            assert provenance == "approximated"
            year = per_year.get(f"FY{window.period.fiscal_year}")
            if window.period.fiscal_period == "Q4" and year is not None:
                assert abs(value - year) <= max(Decimal("0.02"), Decimal("0.03") * abs(year))
                checked += 1

    assert checked >= 5
