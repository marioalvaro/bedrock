"""The earnings review's pure parts (FR-ACC-06; docs/erd/accountability.md "Earnings review"): which
period a report covers, which prior values it restated, which QoE flags changed state, and the
snapshot's line and driver cells at that period. No database, no services: the pickers read any
object shaped like `services/snapshots.py::SnapshotCase`."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from bedrock.analysis.qoe import FlagTable, RuleUnit, Severity
from bedrock.statements.build import StatementTable
from bedrock.statements.periods import Period

PERIOD_SLACK = timedelta(days=10)  # a period end this near the filing's period end is its period
RESTATED_TOLERANCE = Decimal("0.005")  # 0.5% of |before|
RESTATED_LIMIT = 50  # restated cells the payload carries
DRIVER_MISSES = 5

Point = tuple[int, str]  # (fiscal year, fiscal period)


def review_period(periods: Sequence[Period], period_end: date) -> Period | None:
    """The period of `periods` (the annual table's for a 10-K, the quarterly one's for a 10-Q)
    whose `end` is nearest `period_end` and within `PERIOD_SLACK`; of two equally near, the
    earlier end. None when none is that near."""
    near = [p for p in periods if abs(p.end - period_end) <= PERIOD_SLACK]
    return min(near, key=lambda p: (abs(p.end - period_end), p.end), default=None)


@dataclass(frozen=True)
class Restated:
    statement: str
    code: str
    label: str
    unit: str
    fiscal_year: int
    fiscal_period: str
    before: Decimal
    after: Decimal
    pct_change: Decimal | None  # (after - before) / |before|; None when before is 0


def restated(
    before_tables: Sequence[StatementTable], after_tables: Sequence[StatementTable], cutoff: date
) -> list[Restated]:
    """Every cell with a value in both reads, in a period ending before `cutoff`, whose value
    moved by more than `RESTATED_TOLERANCE` of |before| (any move when before is 0). Tables are
    matched by (statement, freq), rows by code, periods by key; the label and unit are the
    read now's. Ordered by |pct_change| descending with nulls last, then statement, code and
    period. All of them: the caller keeps the first `RESTATED_LIMIT`."""
    earlier = {(t.statement, t.freq): t for t in before_tables}
    found = []
    for after in after_tables:
        before = earlier.get((after.statement, after.freq))
        if before is None:
            continue
        old = _cells(before)
        for row in after.rows:
            for period, value in zip(after.periods, row.values, strict=True):
                was = old.get((row.code, period.key))
                if value is None or was is None or period.end >= cutoff:
                    continue
                if not _moved(was, value):
                    continue
                change = None if was == 0 else (value - was) / abs(was)
                found.append(
                    Restated(
                        after.statement,
                        row.code,
                        row.label,
                        row.unit,
                        period.fiscal_year,
                        period.fiscal_period,
                        was,
                        value,
                        change,
                    )
                )
    return sorted(
        found,
        key=lambda r: (
            r.pct_change is None,
            -abs(r.pct_change) if r.pct_change is not None else Decimal(0),
            r.statement,
            r.code,
            r.fiscal_year,
            r.fiscal_period,
        ),
    )


def _cells(table: StatementTable) -> dict[tuple[str, str], Decimal]:
    return {
        (row.code, period.key): value
        for row in table.rows
        for period, value in zip(table.periods, row.values, strict=True)
        if value is not None
    }


def _moved(before: Decimal, after: Decimal) -> bool:
    if before == 0:
        return after != 0
    return abs(after - before) > RESTATED_TOLERANCE * abs(before)


@dataclass(frozen=True)
class FlagChange:
    code: str
    label: str
    unit: RuleUnit
    before: Severity | None  # at the last period of the read before; None: no value
    after: Severity | None  # at the last period of the read now
    value_before: Decimal | None
    value_after: Decimal | None


def flag_changes(before: FlagTable, after: FlagTable) -> list[FlagChange]:
    """Each rule whose severity at the last period of `before` differs from the one at the last
    period of `after`, when at least one of the two is `warn` or `alert`. A rule missing from a
    table, or a table with no periods, reads None there. In `after`'s rule order, then the rules
    of `before` only."""
    old = _last(before)
    new = _last(after)
    codes = [r.code for r in after.rows] + [r.code for r in before.rows if r.code not in new]
    rows = {r.code: r for r in [*before.rows, *after.rows]}  # the read now's label wins
    changes = []
    for code in codes:
        was, was_value = old.get(code, (None, None))
        now, now_value = new.get(code, (None, None))
        if was == now or not ({was, now} & {"warn", "alert"}):
            continue
        rule = rows[code]
        changes.append(FlagChange(code, rule.label, rule.unit, was, now, was_value, now_value))
    return changes


def _last(table: FlagTable) -> dict[str, tuple[Severity | None, Decimal | None]]:
    if not table.periods:
        return {r.code: (None, None) for r in table.rows}
    return {r.code: (r.severity[-1], r.values[-1]) for r in table.rows}


# --- the snapshot's cells ----------------------------------------------------------------------


class CellLike(Protocol):
    @property
    def fiscal_year(self) -> int: ...
    @property
    def fiscal_period(self) -> str: ...
    @property
    def forecast(self) -> Decimal: ...
    @property
    def actual(self) -> Decimal | None: ...
    @property
    def pct_error(self) -> Decimal | None: ...
    @property
    def in_range(self) -> bool | None: ...
    @property
    def source(self) -> str | None: ...


class SeriesLike(Protocol):
    @property
    def code(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def unit(self) -> str: ...
    @property
    def cells(self) -> Sequence[CellLike]: ...


class CaseLike(Protocol):
    @property
    def case(self) -> str: ...
    @property
    def lines(self) -> Sequence[SeriesLike]: ...
    @property
    def drivers(self) -> Sequence[SeriesLike]: ...


@dataclass(frozen=True)
class LinePick:
    forecast: Decimal | None  # Base's
    low: Decimal | None  # min of the three cases' forecasts; None unless all three have one
    high: Decimal | None
    pct_error: Decimal | None  # Base's
    in_range: bool | None


def line_pick(cases: Sequence[CaseLike], code: str, point: Point) -> LinePick:
    """The Base cell of line `code` at `point` and the envelope of the three cases there."""
    cells = {c.case: _cell(c.lines, code, point) for c in cases}
    base = cells.get("base")
    found = [cells.get(c) for c in ("base", "bull", "bear")]
    forecasts = [cell.forecast for cell in found if cell is not None]
    full = len(forecasts) == 3
    return LinePick(
        forecast=None if base is None else base.forecast,
        low=min(forecasts) if full else None,
        high=max(forecasts) if full else None,
        pct_error=None if base is None else base.pct_error,
        in_range=None if base is None else base.in_range,
    )


def _cell(series: Sequence[SeriesLike], code: str, point: Point) -> CellLike | None:
    found = next((s for s in series if s.code == code), None)
    if found is None:
        return None
    return next((c for c in found.cells if (c.fiscal_year, c.fiscal_period) == point), None)


@dataclass(frozen=True)
class DriverMiss:
    code: str
    label: str
    unit: str
    forecast: Decimal
    actual: Decimal | None
    pct_error: Decimal
    in_range: bool | None
    source: str | None


def driver_misses(cases: Sequence[CaseLike], fiscal_year: int) -> list[DriverMiss]:
    """The Base driver cells at (`fiscal_year`, FY) that have a `pct_error`, the
    `DRIVER_MISSES` largest by |pct_error| (ties by code)."""
    base = next((c for c in cases if c.case == "base"), None)
    if base is None:
        return []
    misses = []
    for series in base.drivers:
        cell = _cell([series], series.code, (fiscal_year, "FY"))
        if cell is None or cell.pct_error is None:
            continue
        misses.append(
            DriverMiss(
                series.code,
                series.label,
                series.unit,
                cell.forecast,
                cell.actual,
                cell.pct_error,
                cell.in_range,
                cell.source,
            )
        )
    misses.sort(key=lambda m: (-abs(m.pct_error), m.code))
    return misses[:DRIVER_MISSES]
