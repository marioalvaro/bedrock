"""Synthetic `ForecastHistory`s for the forecast tests: statement tables built straight from
{code: value} per period, so a test states its inputs and hand-computes what it expects."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from functools import cache

from sqlalchemy.orm import Session

from bedrock.forecast.drivers import drivers_for
from bedrock.forecast.history import FLAT, Flat, ForecastHistory, SeriesHistory
from bedrock.forecast.resolve import Resolved, ResolvedDrivers
from bedrock.mapping.config import CanonicalItemDef, load_canonical_items
from bedrock.repositories import engines as engines_repo
from bedrock.statements.build import Row, StatementTable
from bedrock.statements.fiscal_grid import period_dates
from bedrock.statements.periods import Period
from tests.statements_pipeline import run_pipeline

FYE = date(2025, 12, 31)  # a calendar-year company unless a test gives its own dates
Values = Mapping[str, Decimal | int | str | None]


@cache
def _items() -> tuple[CanonicalItemDef, ...]:
    return tuple(load_canonical_items())


def _period(key: str, dates: Mapping[str, tuple[date, date]]) -> Period:
    fiscal_year = int(key[2:6])
    fiscal_period = key[6:] or "FY"
    start, end = dates.get(key) or period_dates(FYE, fiscal_year, fiscal_period)
    label = f"FY{fiscal_year % 100:02d}"
    return Period(
        key,
        label if fiscal_period == "FY" else f"{fiscal_period} {label}",
        fiscal_year,
        fiscal_period,
        start,
        end,
    )


def _tables(
    freq: str, by_period: Mapping[str, Values], dates: Mapping[str, tuple[date, date]]
) -> dict[str, StatementTable]:
    periods = [_period(k, dates) for k in sorted(by_period, key=lambda k: (k[2:6], k[6:]))]
    tables = {}
    for statement in ("IS", "BS", "CF"):
        rows = []
        for item in _items():
            if item.statement != statement:
                continue
            values = [_decimal(by_period[p.key].get(item.code)) for p in periods]
            rows.append(
                Row(
                    item.code,
                    item.label,
                    item.unit,
                    item.kind,
                    0,
                    values,
                    ["reported" if v is not None else None for v in values],
                    [None] * len(values),
                    [None] * len(values),
                )
            )
        tables[statement] = StatementTable(statement, freq, periods, rows, None, [])
    return tables


def _decimal(value: Decimal | int | str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def make_history(
    annual: Mapping[int, Values],
    quarterly: Mapping[str, Values] | None = None,
    series: Sequence[SeriesHistory] = (),
    dates: Mapping[str, tuple[date, date]] | None = None,
) -> ForecastHistory:
    """`annual` by fiscal year, `quarterly` by period key (`FY2026Q2`); `dates` overrides a
    period's (start, end) by key."""
    dates = dates or {}
    annual_tables = _tables("annual", {f"FY{fy}": v for fy, v in annual.items()}, dates)
    periods = annual_tables["IS"].periods
    return ForecastHistory(
        annual=annual_tables,
        quarterly=_tables("quarterly", quarterly or {}, dates),
        segment_series=tuple(series),
        latest_fy_end=periods[-1].end if periods else None,
    )


def complete_sheet(revenue: int = 100) -> dict[str, int]:
    """The values that make a period an opening candidate."""
    return {
        "revenue": revenue,
        "total_assets": 1000,
        "total_liabilities_and_equity": 1000,
        "total_equity": 400,
    }


def fixture_history(ticker: str) -> ForecastHistory:
    """The recorded company's history (no adjustments, so normalized = reported; no segments)."""
    pipeline = run_pipeline(ticker)
    periods = pipeline.annual["IS"].periods
    return ForecastHistory(
        annual=pipeline.annual,
        quarterly=pipeline.quarterly,
        segment_series=(),
        latest_fy_end=periods[-1].end if periods else None,
    )


def resolved(
    by_year: Mapping[int, Mapping[str, Decimal | int | str | Flat]],
    codes: Sequence[str] | None = None,
) -> ResolvedDrivers:
    """A `ResolvedDrivers` with every driver `own`; `codes` defaults to the growth method's."""
    codes = codes or [d.code for d in drivers_for("growth")]
    values: dict[tuple[str, int], Resolved] = {}
    for year, drivers in by_year.items():
        for code in codes:
            value = drivers[code]
            values[(code, year)] = Resolved(
                value if value is FLAT or isinstance(value, Decimal) else Decimal(value), "own"
            )
    return ResolvedDrivers(tuple(codes), tuple(by_year), values, (), frozenset())


def choose_engines(session: Session, scenario_id: int, choices: Mapping[str, str]) -> None:
    """Stores a scenario's engine choices (`mean`, `arima`, …; `auto` deletes the row), for tests
    that assert a number computed from the M4 3-year mean: `choose_engines(s, id, {code: "mean"})`
    pins the driver to it."""
    engines_repo.put(
        session,
        scenario_id,
        {c: None if e == "auto" else e for c, e in choices.items()},
        datetime(2026, 11, 6),
    )
    session.commit()
