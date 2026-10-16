"""Accounting invariants of the normalized view on the real fixtures (AAPL, MSFT, COST, DE), with
seeded random adjustments: quarters still add up to the year, residuals still foot, and balanced
pairs keep the balance sheet as balanced (or as unbalanced) as reported."""

import random
from dataclasses import dataclass
from decimal import Decimal

import pytest

from bedrock.mapping.config import (
    CanonicalItemDef,
    is_adjustable,
    parse_formula,
    propagation_targets,
)
from bedrock.statements.build import StatementTable, build_statement
from tests.statements_pipeline import Pipeline, run_pipeline

TICKERS = ["AAPL", "MSFT", "COST", "DE"]
PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4")
BILLION = 1_000_000_000


@dataclass(frozen=True)
class Adj:
    id: int
    canonical_code: str
    fiscal_year: int
    fiscal_period: str
    amount: Decimal


def build(p: Pipeline, statement: str, freq: str, adjustments: list[Adj]) -> StatementTable:
    return build_statement(p.canonical, p.items, statement, freq, adjustments=adjustments)  # type: ignore[arg-type]


def years(p: Pipeline) -> list[int]:
    """The fiscal years that have a quarterly income statement (and so a Q4)."""
    return sorted({q.fiscal_year for q in p.quarterly["IS"].periods if q.fiscal_period == "Q4"})


def flow_codes(p: Pipeline, statements: tuple[str, ...]) -> list[CanonicalItemDef]:
    return [
        i for i in p.items if i.statement in statements and i.kind == "flow" and is_adjustable(i)
    ]


def random_adjustments(
    rng: random.Random, p: Pipeline, pool: list[CanonicalItemDef], count: int
) -> list[Adj]:
    available = years(p)
    return [
        Adj(
            n,
            rng.choice(pool).code,
            rng.choice(available),
            rng.choice(PERIODS),
            Decimal(rng.randint(-5 * BILLION, 5 * BILLION)),
        )
        for n in range(1, count + 1)
    ]


def column(t: StatementTable, code: str) -> dict[str, Decimal | None]:
    row = next(r for r in t.rows if r.code == code)
    return {p.key: v for p, v in zip(t.periods, row.values, strict=True)}


def year_sums(annual: StatementTable, quarterly: StatementTable, code: str) -> dict[int, bool]:
    """Per fiscal year where the year and its four quarters all have a value: do they add up?"""
    fy, q = column(annual, code), column(quarterly, code)
    out: dict[int, bool] = {}
    for key, value in fy.items():
        year = int(key[2:])
        quarters = [q.get(f"FY{year}Q{n}") for n in (1, 2, 3, 4)]
        if value is not None and all(v is not None for v in quarters):
            out[year] = sum(v for v in quarters if v is not None) == value
    return out


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_quarters_still_add_up_to_the_year_after_random_flow_adjustments(
    ticker: str, seed: int
) -> None:
    p = run_pipeline(ticker)
    adjustments = random_adjustments(
        random.Random(f"{ticker}{seed}"), p, flow_codes(p, ("IS", "CF")), 15
    )
    checked = 0

    for statement in ("IS", "CF"):
        reported = (build(p, statement, "annual", []), build(p, statement, "quarterly", []))
        normalized = (
            build(p, statement, "annual", adjustments),
            build(p, statement, "quarterly", adjustments),
        )
        assert normalized[0].rows != reported[0].rows  # the adjustments did something
        for item in (i for i in p.items if i.statement == statement):
            if item.residual or item.kind != "flow":
                continue  # a residual's quarters are not parts of its year (erd/data.md)
            before = year_sums(*reported, item.code)
            after = year_sums(*normalized, item.code)
            for year, held in before.items():
                if held:
                    assert after.get(year) is True, (statement, item.code, year)
                    checked += 1
    assert checked > 100


def residual_gap(
    t: StatementTable, items: list[CanonicalItemDef], item: CanonicalItemDef, key: str
) -> Decimal | None:
    """residual - its formula, a missing component of its own breakdown counting as 0; None when
    the residual or an operand outside the breakdown has no value in that column."""
    assert item.derive is not None
    index = [p.key for p in t.periods].index(key)
    values = {r.code: r.values[index] for r in t.rows}
    breakdown = {i.code for i in items if i.parent == item.parent}
    total = Decimal(0)
    for sign, code in parse_formula(item.derive):
        value = values.get(code)
        if value is None:
            if code in breakdown:
                continue
            return None
        total += sign * value
    own = values[item.code]
    return None if own is None else own - total


def subtotal_codes(items: list[CanonicalItemDef]) -> set[str | None]:
    """The lines that are a parent or something other lines roll into."""
    return {i.parent for i in items} | {t for i in items for t, _ in i.rolls_into}


def components(items: list[CanonicalItemDef]) -> list[CanonicalItemDef]:
    """Adjustable lines that are neither a parent nor something other lines roll into. An
    adjustment on a subtotal says the total moved without saying which component, so no residual
    absorbs it (erd/data.md: the footing guarantee is for adjustments to components, which roll
    up)."""
    subtotals = subtotal_codes(items)
    return [
        i
        for i in items
        if i.kind in ("flow", "instant") and is_adjustable(i) and i.code not in subtotals
    ]


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_residuals_still_foot_to_their_subtotal_after_random_component_adjustments(
    ticker: str, seed: int
) -> None:
    p = run_pipeline(ticker)
    adjustments = random_adjustments(
        random.Random(f"{ticker}-residual-{seed}"), p, components(p.items), 40
    )
    checked = 0

    for statement in ("IS", "BS", "CF"):
        for freq in ("annual", "quarterly"):
            normalized = build(p, statement, freq, adjustments)
            for item in (i for i in p.items if i.statement == statement and i.residual):
                for period in normalized.periods:
                    gap = residual_gap(normalized, p.items, item, period.key)
                    if gap is not None:
                        assert gap == 0, (statement, freq, item.code, period.key)
                        checked += 1
    assert checked > 100


def side(items: list[CanonicalItemDef], item: CanonicalItemDef) -> str | None:
    """`assets` for a line feeding total assets, `claims` for one feeding liabilities or equity."""
    targets = propagation_targets(items, item.code)
    if item.code == "total_assets" or "total_assets" in targets:
        return "assets"
    if item.code in ("total_liabilities", "total_equity", "temporary_equity"):
        return "claims"
    if "total_liabilities_and_equity" in targets:
        return "claims"
    return None


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_balanced_pairs_leave_the_balance_check_differences_unchanged(
    ticker: str, seed: int
) -> None:
    p = run_pipeline(ticker)
    rng = random.Random(f"{ticker}-pairs-{seed}")
    bs = [i for i in p.items if i.statement == "BS" and is_adjustable(i)]
    assets = [i for i in bs if side(p.items, i) == "assets"]
    claims = [i for i in bs if side(p.items, i) == "claims"]
    reported_q = build(p, "BS", "quarterly", [])
    complete = {
        (q.fiscal_year, q.fiscal_period)
        for q, c in zip(reported_q.periods, reported_q.balance_check or [], strict=True)
        if c.difference is not None
    }
    chosen = sorted(complete)
    adjustments: list[Adj] = []
    for n in range(10):
        year, period = rng.choice(chosen)
        amount = Decimal(rng.randint(-5 * BILLION, 5 * BILLION))
        adjustments.append(Adj(2 * n + 1, rng.choice(assets).code, year, period, amount))
        adjustments.append(Adj(2 * n + 2, rng.choice(claims).code, year, period, amount))

    for freq in ("annual", "quarterly"):
        reported = build(p, "BS", freq, [])
        normalized = build(p, "BS", freq, adjustments)
        assert reported.balance_check is not None and normalized.balance_check is not None
        assert normalized.rows != reported.rows  # the pairs did something
        assert [c.difference for c in normalized.balance_check] == [
            c.difference for c in reported.balance_check
        ], freq


@pytest.mark.parametrize("ticker", TICKERS)
def test_an_adjustment_on_a_line_empty_in_its_pair_keeps_totals_adding_up_and_footing(
    ticker: str,
) -> None:
    """The reported Q4 (or year) of such a line is hidden inside its breakdown's residual, so the
    delta that reaches the totals in that period must also reach the residual: Q1..Q4 = FY of every
    total, and components + residual = subtotal as before (erd/data.md, "Empty cells")."""
    p = run_pipeline(ticker)
    exercised = 0

    for statement in ("IS", "CF"):
        annual0, quarterly0 = (
            build(p, statement, "annual", []),
            build(p, statement, "quarterly", []),
        )
        residuals = [i for i in p.items if i.statement == statement and i.residual]
        # An adjustment on a subtotal (a parent, or a line others roll into) says the total moved
        # without saying which component, so no residual absorbs it: erd/data.md "no residual
        # absorbs a subtotal adjustment". Their Q1..Q4 = FY is still asserted, their footing not.
        subtotals = subtotal_codes(p.items)
        for item in (
            i for i in p.items if i.statement == statement and i in flow_codes(p, (statement,))
        ):
            fy, qs = column(annual0, item.code), column(quarterly0, item.code)
            for year in years(p):
                fy_value, q4_value = fy.get(f"FY{year}"), qs.get(f"FY{year}Q4")
                cases = (
                    ("FY", fy_value is not None and q4_value is None),  # Q4 hidden in a residual
                    (
                        "Q2",
                        qs.get(f"FY{year}Q2") is not None and fy_value is None,
                    ),  # so is the year
                )
                for period, empty_pair in cases:
                    if not empty_pair:
                        continue
                    exercised += 1
                    adjustments = [Adj(1, item.code, year, period, Decimal(BILLION))]
                    annual1 = build(p, statement, "annual", adjustments)
                    quarterly1 = build(p, statement, "quarterly", adjustments)
                    where = (item.code, year, period)
                    for target in propagation_targets(p.items, item.code):
                        if year_sums(annual0, quarterly0, target).get(year):
                            assert year_sums(annual1, quarterly1, target).get(year), (
                                *where,
                                target,
                            )
                    if item.code in subtotals:
                        continue
                    for before, after in ((annual0, annual1), (quarterly0, quarterly1)):
                        for residual in residuals:
                            for period_ in after.periods:
                                if residual_gap(before, p.items, residual, period_.key) == 0:
                                    gap = residual_gap(after, p.items, residual, period_.key)
                                    assert gap in (0, None), (*where, residual.code, period_.key)
    assert exercised > 0
