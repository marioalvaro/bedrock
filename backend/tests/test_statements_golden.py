"""Statements built from the recorded companyfacts fixtures, against the 10-Ks (M1 S3).

Goldens live in `tests/golden/statements/<TICKER>.yaml` and come from the 10-K documents, never
from companyfacts. Values use the displayed sign convention (expenses positive, capex negative).
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from bedrock.mapping.config import parse_formula
from bedrock.mapping.gaps import missing_items
from bedrock.statements.build import StatementTable
from tests.statements_pipeline import Pipeline, run_pipeline

GOLDEN_DIR = Path(__file__).parent / "golden" / "statements"
TICKERS = ["AAPL", "MSFT", "COST"]
USD_TOLERANCE = Decimal(500_000)
EPS_TOLERANCE = Decimal("0.005")
MIN_FISCAL_YEARS = 10


def golden(ticker: str) -> dict[str, Any]:
    loaded = yaml.safe_load((GOLDEN_DIR / f"{ticker}.yaml").read_text())
    assert isinstance(loaded, dict)
    return loaded


def value_at(table: StatementTable, code: str, period_key: str) -> Decimal | None:
    row = next(r for r in table.rows if r.code == code)
    index = [p.key for p in table.periods].index(period_key)
    return row.values[index]


def tolerance(pipeline: Pipeline, code: str) -> Decimal:
    unit = next(i.unit for i in pipeline.items if i.code == code)
    return EPS_TOLERANCE if unit == "USD/shares" else USD_TOLERANCE


def table_with(pipeline: Pipeline, code: str, freq: str) -> StatementTable:
    statement = next(i.statement for i in pipeline.items if i.code == code)
    return (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]


@pytest.mark.parametrize("ticker", TICKERS)
def test_annual_values_match_the_10k(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    mismatches = []
    for period_key, expected in golden(ticker)["annual"].items():
        for code, figure in expected.items():
            actual = value_at(table_with(pipeline, code, "annual"), code, period_key)
            if actual is None or abs(actual - Decimal(str(figure))) > tolerance(pipeline, code):
                mismatches.append(f"{period_key} {code}: 10-K {figure}, mapped {actual}")
    assert mismatches == []


@pytest.mark.parametrize("ticker", TICKERS)
def test_derived_q4_matches_the_10k(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    mismatches = []
    for period_key, expected in golden(ticker)["quarterly"].items():
        for code, figure in expected.items():
            actual = value_at(table_with(pipeline, code, "quarterly"), code, period_key)
            if actual is None or abs(actual - Decimal(str(figure))) > tolerance(pipeline, code):
                mismatches.append(f"{period_key} {code}: 10-K {figure}, mapped {actual}")
    assert mismatches == []


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_balance_sheet_balances_in_every_period(ticker: str, freq: str) -> None:
    """Every period from the first full balance sheet on balances. The earliest periods lack one:
    XBRL balance sheets start with FY2008-09, older columns only exist as comparatives of other
    statements (an equity statement's opening balance, cash flow cash), and Costco did not present
    total liabilities before FY2009. Those periods must come first."""
    pipeline = run_pipeline(ticker)
    table = (pipeline.annual if freq == "annual" else pipeline.quarterly)["BS"]
    assert table.balance_check, "no balance sheet periods at all"
    totals = [
        next(r for r in table.rows if r.code == code)
        for code in ("total_assets", "total_liabilities", "total_equity")
    ]
    keys = [p.key for p in table.periods]
    first_full = next(i for i in range(len(keys)) if all(t.values[i] is not None for t in totals))

    unbalanced = [
        (c.period_key, c.difference)
        for i, c in enumerate(table.balance_check)
        if i >= first_full and not c.ok
    ]

    assert unbalanced == []
    assert first_full <= 3, f"too many periods without a full balance sheet: {keys[:first_full]}"


@pytest.mark.parametrize("ticker", TICKERS)
def test_quarters_sum_to_the_fiscal_year(ticker: str) -> None:
    """Q1+Q2+Q3+Q4 = FY for every flow line of every year that has all four quarters. Residual
    lines are left out: a residual is its subtotal less the components that have a value in that
    column, and a component can be present in the 10-K and absent from a 10-Q (zero amounts are
    often omitted), so a quarter's residual is not a part of the year's. They keep the accounting
    identity instead (see the next test)."""
    pipeline = run_pipeline(ticker)
    flow_codes = [i.code for i in pipeline.items if i.kind == "flow" and not i.residual]
    checked = 0
    failures = []
    for code in flow_codes:
        a_table = table_with(pipeline, code, "annual")
        q_table = table_with(pipeline, code, "quarterly")
        q_keys = [p.key for p in q_table.periods]
        for period in a_table.periods:
            quarters = [
                value_at(q_table, code, f"{period.key}Q{n}")
                if f"{period.key}Q{n}" in q_keys
                else None
                for n in (1, 2, 3, 4)
            ]
            fy = value_at(a_table, code, period.key)
            if fy is None or any(q is None for q in quarters):
                continue
            checked += 1
            total = sum((q for q in quarters if q is not None), Decimal(0))
            if abs(total - fy) > USD_TOLERANCE:
                failures.append(f"{code} {period.key}: quarters {total}, FY {fy}")
    assert checked > 0, "no year had all four quarters"
    assert failures == []


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_residual_lines_complete_their_subtotal_in_every_period(ticker: str, freq: str) -> None:
    pipeline = run_pipeline(ticker)
    failures = []
    checked = 0
    for item in pipeline.items:
        if not item.residual or item.derive is None:
            continue
        table = table_with(pipeline, item.code, freq)
        rows = {r.code: r for r in table.rows}
        terms = parse_formula(item.derive)
        for index, period in enumerate(table.periods):
            subtotal = rows[terms[0][1]].values[index]
            if subtotal is None:
                continue
            expected = sum(
                (sign * (rows[code].values[index] or Decimal(0)) for sign, code in terms),
                Decimal(0),
            )
            checked += 1
            if rows[item.code].values[index] != expected:
                failures.append(f"{item.code} {period.key}")
    assert checked > 0
    assert failures == []


@pytest.mark.parametrize("ticker", TICKERS)
def test_at_least_ten_fiscal_years_of_revenue_and_assets(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    income, balance = pipeline.annual["IS"], pipeline.annual["BS"]
    both = [
        p.key
        for p in income.periods
        if value_at(income, "revenue", p.key) is not None
        and p.key in [b.key for b in balance.periods]
        and value_at(balance, "total_assets", p.key) is not None
    ]
    assert len(both) >= MIN_FISCAL_YEARS


@pytest.mark.parametrize("ticker", TICKERS)
def test_missing_items_equal_the_expected_missing_list(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    missing = sorted(m.code for m in missing_items(pipeline.annual, pipeline.items))
    assert missing == sorted(golden(ticker)["expected_missing"])


SUBTOTAL_SPLITS = [
    ("IS", "total_operating_costs", ["rnd", "sga", "other_operating_expenses"]),
    ("BS", "total_assets", ["total_current_assets", "total_noncurrent_assets"]),
    ("BS", "total_liabilities", ["total_current_liabilities", "total_noncurrent_liabilities"]),
]


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
@pytest.mark.parametrize(("statement", "total", "parts"), SUBTOTAL_SPLITS)
def test_a_subtotal_equals_the_sum_of_its_breakdown(
    ticker: str, freq: str, statement: str, total: str, parts: list[str]
) -> None:
    pipeline = run_pipeline(ticker)
    table = (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]
    rows = {r.code: r for r in table.rows}
    checked = 0
    failures = []
    for index, period in enumerate(table.periods):
        whole = rows[total].values[index]
        pieces = [rows[code].values[index] for code in parts]
        if whole is None or all(p is None for p in pieces):
            continue  # a missing part (Costco has no R&D) counts as zero, as in a residual
        checked += 1
        if abs(whole - sum((p for p in pieces if p is not None), Decimal(0))) > USD_TOLERANCE:
            failures.append(period.key)
    assert checked > 0, f"{total} never had a breakdown"
    assert failures == []


COMPUTED_TOTALS = [
    ("CF", "free_cash_flow", [(1, "cfo"), (1, "capex")]),
    ("BS", "total_debt", [(1, "short_term_debt"), (1, "long_term_debt")]),
    (
        "BS",
        "net_debt",
        [
            (1, "short_term_debt"),
            (1, "long_term_debt"),
            (-1, "cash"),
            (-1, "short_term_investments"),
        ],
    ),
]


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
@pytest.mark.parametrize(("statement", "code", "terms"), COMPUTED_TOTALS)
def test_free_cash_flow_total_debt_and_net_debt_follow_their_lines(
    ticker: str, freq: str, statement: str, code: str, terms: list[tuple[int, str]]
) -> None:
    pipeline = run_pipeline(ticker)
    table = (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]
    rows = {r.code: r for r in table.rows}
    checked = 0
    failures = []
    for index, period in enumerate(table.periods):
        operands = [rows[c].values[index] for _, c in terms]
        actual = rows[code].values[index]
        if any(o is None for o in operands):
            assert actual is None, f"{code} {period.key} has a value with a missing operand"
            continue
        checked += 1
        expected = sum(
            (sign * (o or Decimal(0)) for (sign, _), o in zip(terms, operands, strict=True)),
            Decimal(0),
        )
        if actual != expected:
            failures.append(f"{code} {period.key}: {actual} != {expected}")
    assert checked > 0, f"{code} never had all its operands"
    assert failures == []
