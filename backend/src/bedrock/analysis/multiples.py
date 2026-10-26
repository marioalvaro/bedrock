"""Company-list key stats (FR-WS-01). Pure: statement tables and a price in, numbers out."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

from bedrock.ratios.calculator import RatioRow, RatioTable
from bedrock.ratios.registry import Unit
from bedrock.statements.build import RATIO_PLACES, StatementTable
from bedrock.statements.periods import Period

MULTIPLE_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class KeyStats:
    price: Decimal | None
    price_date: date | None
    market_cap: Decimal | None
    pe: Decimal | None
    ev_ebitda: Decimal | None
    revenue_growth: Decimal | None


def key_stats(
    *,
    close: tuple[date, Decimal] | None,
    shares: Decimal | None,
    ttm: Mapping[str, StatementTable],
    quarterly_bs: StatementTable | None,
) -> KeyStats:
    """`ttm` holds the TTM tables by statement (IS, CF); `quarterly_bs` the quarterly balance
    sheet. Each stat is null when an input is missing or its denominator is not positive. The TTM
    figures are the latest TTM period's, and the balance sheet is read at the quarter it ends."""
    price_date, price = (None, None) if close is None else close
    market_cap = (
        None if price is None or shares is None else (price * shares).quantize(MULTIPLE_PLACES)
    )

    income = ttm.get("IS")
    period = income.periods[-1] if income is not None and income.periods else None
    revenue_growth = _value(income, "revenue", period, field="yoy")
    net_income = _value(income, "net_income_common", period)
    ebitda = _sum(
        _value(income, "operating_income", period), _value(ttm.get("CF"), "d_and_a", period)
    )

    return KeyStats(
        price=price,
        price_date=price_date,
        market_cap=market_cap,
        pe=_multiple(market_cap, net_income),
        ev_ebitda=_multiple(_enterprise_value(market_cap, quarterly_bs, period), ebitda),
        revenue_growth=revenue_growth,
    )


def balance_sheet_shares(*tables: StatementTable) -> Decimal | None:
    """The `shares_outstanding` of the latest period any of the balance sheets has a value for,
    for a company with no cover-page (`dei`) count."""
    found: list[tuple[date, Decimal]] = []
    for table in tables:
        row = next((r for r in table.rows if r.code == "shares_outstanding"), None)
        if row is not None:
            found += [(p.end, v) for p, v in zip(table.periods, row.values, strict=True) if v]
    return max(found, key=lambda f: f[0])[1] if found else None


def _enterprise_value(
    market_cap: Decimal | None, balance_sheet: StatementTable | None, ttm_period: Period | None
) -> Decimal | None:
    if market_cap is None or balance_sheet is None or ttm_period is None:
        return None
    at = next(
        (
            p
            for p in balance_sheet.periods
            if (p.fiscal_year, p.fiscal_period)
            == (ttm_period.fiscal_year, ttm_period.fiscal_period)
        ),
        None,
    )
    debt = [_value(balance_sheet, code, at) for code in ("short_term_debt", "long_term_debt")]
    cash = [_value(balance_sheet, code, at) for code in ("cash", "short_term_investments")]
    if any(v is None for v in debt + cash):
        return None
    return (
        market_cap
        + sum((v for v in debt if v is not None), Decimal(0))
        - sum((v for v in cash if v is not None), Decimal(0))
    )


def _value(
    table: StatementTable | None, code: str, period: Period | None, *, field: str = "values"
) -> Decimal | None:
    """One row's `values` (or `yoy`) entry at `period`, matched by key."""
    if table is None or period is None:
        return None
    row = next((r for r in table.rows if r.code == code), None)
    if row is None:
        return None
    for p, value in zip(table.periods, getattr(row, field), strict=True):
        if p.key == period.key:
            return value  # type: ignore[no-any-return]
    return None


def _sum(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a + b


def _multiple(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return (numerator / denominator).quantize(MULTIPLE_PLACES)


MIN_HISTORY = 3  # annual values needed before a range and percentile are shown


@dataclass(frozen=True)
class MultipleSummary:
    """One valuation ratio: its current value and the range of its annual history."""

    code: str
    label: str
    unit: Unit
    caveat: str | None
    current: Decimal | None
    min: Decimal | None
    median: Decimal | None
    max: Decimal | None
    percentile: Decimal | None  # share of the history that is <= current, 0..1
    n: int  # annual values used


def valuation_summary(history: RatioTable, current: RatioTable) -> list[MultipleSummary]:
    """A summary per Valuation ratio, in registry order. `history` is the annual ratio table
    and `current` a table whose last period holds the current values (TTM at the latest close).
    The range uses the annual values, leaving out null ones and, for `x` multiples, those <= 0.
    With fewer than `MIN_HISTORY` values there is no range or percentile."""
    now = {row.code: row for row in current.rows}
    result = []
    for row in history.rows:
        if row.category != "Valuation":
            continue
        latest = _last(now.get(row.code))
        past = [v for v in row.values if v is not None and (row.unit != "x" or v > 0)]
        ranged = len(past) >= MIN_HISTORY
        result.append(
            MultipleSummary(
                code=row.code,
                label=row.label,
                unit=row.unit,
                caveat=row.caveat,
                current=latest,
                min=min(past) if ranged else None,
                median=median(past).quantize(RATIO_PLACES) if ranged else None,
                max=max(past) if ranged else None,
                percentile=(
                    (Decimal(sum(v <= latest for v in past)) / len(past)).quantize(RATIO_PLACES)
                    if ranged and latest is not None
                    else None
                ),
                n=len(past),
            )
        )
    return result


def _last(row: RatioRow | None) -> Decimal | None:
    return None if row is None or not row.values else row.values[-1]
