"""Stored forecast rows against the latest actuals (docs/erd/accountability.md "Scoring"). Pure;
scores are computed on read, so nothing here is ever stored."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from bedrock.backtest.snapshot import RowKind, ValueRow
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    annual_driver_values,
    scenario_drivers,
)
from bedrock.statements.build import StatementTable
from bedrock.statements.splits import PER_SHARE, SHARES, Split, adjust, split_factor

SCORED_CODES = (
    "revenue",
    "operating_income",
    "net_income",
    "eps_diluted",
    "free_cash_flow",
    "cash",
    "total_debt",
)
# An `approximated` cell (Q4 share counts and EPS) is never an actual (FR-DATA-14).
ACTUAL_PROVENANCE = frozenset({"reported", "derived", "normalized", "zero_inferred", "imported"})
CASES = ("base", "bull", "bear")

LineKey = tuple[str, int, str]  # (code, fiscal year, fiscal period)
Freq = Literal["annual", "quarterly"]


@dataclass(frozen=True)
class Scored:
    kind: RowKind
    code: str
    fiscal_year: int
    fiscal_period: str
    horizon: int
    forecast: Decimal  # in today's shares
    actual: Decimal
    pct_error: Decimal | None  # (forecast - actual) / |actual|; None when the actual is 0
    in_range: bool | None  # None: the row has no range


@dataclass(frozen=True)
class SummaryRow:
    kind: RowKind
    code: str
    method: str  # the engine code of a backtest, the case of a snapshot
    freq: Freq
    horizon: int
    n: int  # scored rows of the group, a zero actual included
    mape: Decimal | None  # over the non-null `pct_error`s
    bias: Decimal | None  # positive: the forecasts ran high
    hit_rate: Decimal | None  # in range / `n_range`; None when `n_range` is 0
    n_range: int  # scored rows that have a range


def line_actuals(history: ForecastHistory) -> dict[LineKey, Decimal]:
    """Every annual and quarterly cell whose provenance can be compared with a forecast."""
    actuals: dict[LineKey, Decimal] = {}
    for tables in (history.annual, history.quarterly):
        for table in tables.values():
            actuals.update(_table_actuals(table))
    return actuals


def driver_actuals(
    history: ForecastHistory, settings: ScenarioSettings, years: Sequence[int]
) -> dict[tuple[str, int], Decimal]:
    """Each driver of the run's settings in each of `years` where the history gives a value."""
    values = annual_driver_values(history, settings, years)
    return {key: value for key, value in values.items() if value is not None}


def units_of(history: ForecastHistory, settings: ScenarioSettings) -> dict[str, str]:
    """The unit of every statement line and driver of the settings, by code."""
    units = {row.code: row.unit for table in history.annual.values() for row in table.rows}
    return units | {d.code: d.unit for d in scenario_drivers(history, settings)}


def line_ranges(
    cases: Mapping[str, Sequence[ValueRow]],
) -> dict[LineKey, tuple[Decimal, Decimal]]:
    """The (min, max) of the three case points at each period every case has a line row for."""
    if any(case not in cases for case in CASES):
        return {}
    points: list[dict[LineKey, Decimal]] = [
        {_key(r): r.point for r in cases[case] if r.kind == "line"} for case in CASES
    ]
    shared = set(points[0]).intersection(*points[1:])
    return {key: (min(p[key] for p in points), max(p[key] for p in points)) for key in shared}


def score_run(
    rows: Sequence[ValueRow],
    lines: Mapping[LineKey, Decimal],
    drivers: Mapping[tuple[str, int], Decimal],
    units: Mapping[str, str],
    created: date,
    actions: Sequence[Split],
    ranges: Mapping[LineKey, tuple[Decimal, Decimal]] | None = None,
    case: str | None = None,
) -> list[Scored]:
    """One `Scored` per row with an actual, the forecast restated by the splits after `created`.
    A driver is in range inside its band; a line only when `case` is `base` and `ranges` has its
    period. A row with no actual needs no unit (a segment series deleted since has neither)."""
    factor = split_factor(created, actions)
    scored = []
    for row in rows:
        actual = (
            lines.get(_key(row)) if row.kind == "line" else drivers.get((row.code, row.fiscal_year))
        )
        if actual is None:
            continue
        unit = units[row.code]
        forecast = _today(row.point, unit, factor)
        band = _band(row, ranges, case)
        scored.append(
            Scored(
                row.kind,
                row.code,
                row.fiscal_year,
                row.fiscal_period,
                row.horizon,
                forecast,
                actual,
                None if actual == 0 else (forecast - actual) / abs(actual),
                None
                if band is None
                else _today(band[0], unit, factor) <= actual <= _today(band[1], unit, factor),
            )
        )
    return scored


def summarize(method: str, scored: Sequence[Scored]) -> list[SummaryRow]:
    """One row per (kind, code, frequency, horizon), sorted by them."""
    groups: dict[tuple[RowKind, str, Freq, int], list[Scored]] = {}
    for item in scored:
        freq: Freq = "annual" if item.fiscal_period == "FY" else "quarterly"
        groups.setdefault((item.kind, item.code, freq, item.horizon), []).append(item)
    return [_summary(method, key, groups[key]) for key in sorted(groups)]


def _table_actuals(table: StatementTable) -> dict[LineKey, Decimal]:
    actuals = {}
    for row in table.rows:
        cells = zip(table.periods, row.values, row.provenance, strict=True)
        for period, value, provenance in cells:
            if value is not None and provenance in ACTUAL_PROVENANCE:
                actuals[(row.code, period.fiscal_year, period.fiscal_period)] = value
    return actuals


def _key(row: ValueRow) -> LineKey:
    return (row.code, row.fiscal_year, row.fiscal_period)


def _band(
    row: ValueRow,
    ranges: Mapping[LineKey, tuple[Decimal, Decimal]] | None,
    case: str | None,
) -> tuple[Decimal, Decimal] | None:
    if row.kind == "driver":
        return None if row.p05 is None or row.p95 is None else (row.p05, row.p95)
    return None if case != "base" or ranges is None else ranges.get(_key(row))


def _today(value: Decimal, unit: str, factor: Decimal) -> Decimal:
    """`value` in today's shares. Only a share or per-share value changes with a split (`adjust`
    would divide a USD one)."""
    return adjust(value, unit, factor) if unit in (SHARES, PER_SHARE) else value


def _summary(
    method: str, key: tuple[RowKind, str, Freq, int], items: Sequence[Scored]
) -> SummaryRow:
    kind, code, freq, horizon = key
    errors = [i.pct_error for i in items if i.pct_error is not None]
    ranged = [i.in_range for i in items if i.in_range is not None]
    return SummaryRow(
        kind,
        code,
        method,
        freq,
        horizon,
        len(items),
        _mean([abs(e) for e in errors]),
        _mean(errors),
        Decimal(sum(ranged)) / len(ranged) if ranged else None,
        len(ranged),
    )


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / len(values) if values else None
