"""The rule engine over the four recorded companyfacts fixtures (docs/erd/data.md "Rule engine"):
properties every filled cell must have, and the fills the identities and the NCI rule are known to
make. The never-replace guard is `test_mapping_baseline_guard.py`."""

from decimal import Decimal
from functools import cache

import pytest

from bedrock.statements.build import build_statement
from bedrock.statements.cell_types import Cell, CellKey
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import BALANCE_FLOOR, BALANCE_RELATIVE
from tests.statements_pipeline import run_pipeline

TICKERS = ["AAPL", "MSFT", "COST", "DE"]


@cache
def solved(ticker: str) -> SolvedCells:
    p = run_pipeline(ticker)
    return solve_cells(p.canonical, p.items, fiscal_calendar(p.canonical), p.rules)


def period_keys(cells: dict[CellKey, Cell]) -> list[str]:
    return sorted({key for _, key in cells})


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_solved_cell_satisfies_its_identity(ticker: str) -> None:
    p = run_pipeline(ticker)
    identities = {i.id: i for i in p.identities}
    cells = solved(ticker).cells
    solved_cells = [(key, c) for key, c in cells.items() if c.solved_by is not None]

    assert solved_cells, "the fixture should exercise at least one identity"
    for (code, period), cell in solved_cells:
        identity = identities[cell.solved_by or ""]
        terms = [(coef, cells[(c, period)].value) for coef, c in identity.terms]
        assert all(v is not None for _, v in terms), (code, period)
        total = sum((coef * v for coef, v in terms if v is not None), Decimal(0))
        if cell.provenance == "zero_inferred":
            largest = max(abs(v) for _, v in terms if v is not None)
            assert abs(total) <= max(BALANCE_FLOOR, BALANCE_RELATIVE * largest), (code, period)
        else:
            assert total == 0, (identity.id, code, period, total)


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_inferred_zero_is_exactly_zero(ticker: str) -> None:
    inferred = [c for c in solved(ticker).cells.values() if c.provenance == "zero_inferred"]

    assert all(c.value == Decimal(0) for c in inferred)
    assert all(c.derivation is not None and c.source is None for c in inferred)


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_four_quarters_still_add_up_to_the_year_for_every_flow(ticker: str) -> None:
    p = run_pipeline(ticker)
    cells = solved(ticker).cells
    off: list[str] = []
    for item in p.items:
        if item.kind != "flow" or item.residual:
            continue
        for year in {key[2:6] for _, key in cells if key.startswith("FY")}:
            parts = [cells.get((item.code, f"FY{year}Q{n}")) for n in (1, 2, 3, 4)]
            fiscal = cells.get((item.code, f"FY{year}"))
            if (
                fiscal is None
                or fiscal.value is None
                or any(c is None or c.value is None for c in parts)
            ):
                continue
            total = sum(
                (c.value for c in parts if c is not None and c.value is not None), Decimal(0)
            )
            if total != fiscal.value:
                off.append(f"{item.code} FY{year}: {total} != {fiscal.value}")

    assert off == [], "\n".join(off[:10])


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_balance_check_and_the_cash_roll_forward_pass_wherever_they_did(ticker: str) -> None:
    p = run_pipeline(ticker)
    for freq in ("annual", "quarterly"):
        before = build_statement(p.canonical, p.items, "BS", freq)  # type: ignore[arg-type]
        after = (p.annual if freq == "annual" else p.quarterly)["BS"]
        assert before.balance_check is not None and after.balance_check is not None
        was_ok = {c.period_key for c in before.balance_check if c.ok}
        now_ok = {c.period_key for c in after.balance_check if c.ok}
        assert was_ok <= now_ok, sorted(was_ok - now_ok)

        cash_before = _roll_forward(build_statement(p.canonical, p.items, "CF", freq))  # type: ignore[arg-type]
        cash_after = _roll_forward((p.annual if freq == "annual" else p.quarterly)["CF"])
        assert {k for k, ok in cash_before.items() if ok} <= {
            k for k, ok in cash_after.items() if ok
        }


def _roll_forward(table) -> dict[str, bool]:  # type: ignore[no-untyped-def]
    rows = {r.code: r.values for r in table.rows}
    out = {}
    for i, period in enumerate(table.periods):
        parts = [rows[c][i] for c in ("net_change_in_cash", "cfo", "cfi", "cff", "fx_effect")]
        if any(v is None for v in parts):
            continue
        change, cfo, cfi, cff, fx = parts
        largest = max(abs(v) for v in parts)
        out[period.key] = abs(change - (cfo + cfi + cff + fx)) <= max(
            BALANCE_FLOOR, BALANCE_RELATIVE * largest
        )
    return out


# --- the fills the rules are known to make -------------------------------------------------


def cell(ticker: str, code: str, period: str) -> Cell:
    return solved(ticker).cells[(code, period)]


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT"])
@pytest.mark.parametrize("code", ["nci", "net_income_nci"])
def test_a_filer_that_tags_no_nci_gets_inferred_zeros(ticker: str, code: str) -> None:
    for period in ("FY2024", "FY2020", "FY2024Q4", "FY2023Q2"):
        found = cell(ticker, code, period)
        assert (found.value, found.provenance) == (Decimal(0), "zero_inferred"), (code, period)


def test_deere_reports_its_noncontrolling_interest_so_nothing_is_inferred() -> None:
    cells = solved("DE").cells

    assert not any(
        c.provenance == "zero_inferred" and k[0] in ("nci", "net_income_nci")
        for k, c in cells.items()
    )


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST"])
def test_temporary_equity_is_an_inferred_zero_where_the_balance_sheet_foots(ticker: str) -> None:
    found = cell(ticker, "temporary_equity", "FY2024")

    assert (found.value, found.provenance, found.solved_by) == (
        Decimal(0),
        "zero_inferred",
        "balance_sheet",
    )


def test_apple_fx_effect_is_solved_within_five_percent_and_the_rest_are_warnings() -> None:
    result = solved("AAPL")
    fx = [(k, c) for k, c in result.cells.items() if k[0] == "fx_effect" and c.solved_by]

    assert fx
    for (_, period), found in fx:
        parts = [
            result.cells[(c, period)].value for c in ("net_change_in_cash", "cfo", "cfi", "cff")
        ]
        largest = max(abs(v) for v in parts if v is not None)
        assert found.value is not None and abs(found.value) <= Decimal("0.05") * largest
    rejected = [w for w in result.warnings if w.rule == "cash_rollforward"]
    assert rejected
    for w in rejected:
        assert result.cells[("fx_effect", w.period_key)].value is None
        assert w.code == "fx_effect"
        # either the 5% bound refused a value, or the operands came from different filings (G13)
        assert w.value is not None or "different filings" in w.reason


@pytest.mark.parametrize("ticker", TICKERS)
def test_a_derived_total_liabilities_never_sits_beside_a_reported_temporary_equity(
    ticker: str,
) -> None:
    """S7 known issue: `total_liabilities` falls back to L&E - equity, which would count temporary
    equity as a liability. The fixtures never combine the two (Deere tags `Liabilities` in every
    year), so the fallback stands; this fails the day one does."""
    p = run_pipeline(ticker)
    for tables in (p.annual, p.quarterly):
        rows = {r.code: r for r in tables["BS"].rows}
        for i, provenance in enumerate(rows["total_liabilities"].provenance):
            if provenance == "derived":
                assert not rows["temporary_equity"].values[i], tables["BS"].periods[i].key
