"""Integrity checks of a forecast (docs/erd/forecasting.md "Tier 1 driver model" → Integrity,
FR-FCST-06). Pure."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bedrock.forecast.engines.driver import ForecastStatements

TOLERANCE = Decimal("0.01")  # USD
ZERO = Decimal(0)


@dataclass(frozen=True)
class IntegrityCheck:
    period_key: str
    balance_diff: Decimal  # total_assets - total_liabilities_and_equity
    cash_diff: Decimal  # cash - previous cash - net_change_in_cash
    re_diff: Decimal  # retained_earnings - previous RE - NI common + dividends + buybacks
    quarters_diff: Decimal | None  # an FY built from quarters: max |FY - sum of quarters|
    ok: bool


def check(statements: ForecastStatements) -> list[IntegrityCheck]:
    """One check per forecast period, in the statements' order. A quarter rolls forward from the
    previous quarter (the first from the opening), a year from the previous year (the first from
    the opening). A year built from quarters rolls forward over its forecast quarters only, from
    the balance before the first of them (its actual quarters are history)."""
    opening = statements.opening
    start = (opening.balance["cash"], opening.balance["retained_earnings"])
    previous_quarter = previous_year = start
    year_start: dict[int, tuple[Decimal, Decimal]] = {}
    checks = []
    for period in statements.periods:
        end = (
            statements.get("cash", period.key) or ZERO,
            statements.get("retained_earnings", period.key) or ZERO,
        )
        if period.fiscal_period != "FY":
            year_start.setdefault(period.fiscal_year, previous_quarter)
            checks.append(_check(statements, period.key, previous_quarter, [period.key], None))
            previous_quarter = end
            continue
        quarters = [
            q.key
            for q in statements.periods
            if q.fiscal_year == period.fiscal_year and q.fiscal_period != "FY"
        ]
        if quarters:
            in_progress = opening.period.fiscal_year == period.fiscal_year
            actual = opening.year_to_date if in_progress else {}
            diff = max(
                (
                    abs(fy - (actual.get(code) or ZERO) - _total(statements, code, quarters))
                    for code in statements.flow_codes
                    if (fy := statements.get(code, period.key)) is not None
                ),
                default=ZERO,
            )
            checks.append(
                _check(statements, period.key, year_start[period.fiscal_year], quarters, diff)
            )
        else:
            checks.append(_check(statements, period.key, previous_year, [period.key], None))
        previous_year = end
    return checks


def _check(
    statements: ForecastStatements,
    key: str,
    previous: tuple[Decimal, Decimal],
    flows: list[str],
    quarters_diff: Decimal | None,
) -> IntegrityCheck:
    """`flows`: the periods whose flows roll `previous` (cash, retained earnings) forward to the
    end of `key`."""

    def value(code: str) -> Decimal:
        return statements.get(code, key) or ZERO

    def flow(code: str) -> Decimal:
        return _total(statements, code, flows)

    balance = value("total_assets") - value("total_liabilities_and_equity")
    cash = value("cash") - previous[0] - flow("net_change_in_cash")
    # dividends_paid and buybacks are displayed negative
    earnings = (
        value("retained_earnings")
        - previous[1]
        - flow("net_income_common")
        - flow("dividends_paid")
        - flow("buybacks")
    )
    diffs = [balance, cash, earnings] + ([] if quarters_diff is None else [quarters_diff])
    return IntegrityCheck(
        key, balance, cash, earnings, quarters_diff, all(abs(d) <= TOLERANCE for d in diffs)
    )


def _total(statements: ForecastStatements, code: str, keys: list[str]) -> Decimal:
    return sum((statements.get(code, k) or ZERO for k in keys), ZERO)
