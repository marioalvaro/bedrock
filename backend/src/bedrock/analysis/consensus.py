"""Analyst consensus as guidance (docs/erd/analysis.md "Consensus guidance"). Yahoo
labels its estimates by relative period (0q, +1q: the next two quarters to report; 0y, +1y: the
current and next fiscal year), and those labels lag the fiscal calendar around a report. So a
`0` row is placed by its year-ago revenue: the stored period whose revenue matches it within 1 %
is the year before, and the estimate is the period a year after it; the `+1` row is the period
after its `0` row. Only the periods a `0` row can refer to are candidates: for `0y` the latest
stored fiscal year or the one before (Yahoo lagging a 10-K), for `0q` the quarter two to four
before the latest stored one (3 normally, 4 when Yahoo lags a report, 2 when Bedrock has not
fetched the latest filing yet); an older match is a coincidence (DE's equipment-only year-ago
revenue matches its FY19 total). A row that matches nothing is left out, never guessed. Pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

TOLERANCE = Decimal("0.01")
# How far Yahoo's calendar quarter end may be from the fiscal quarter's end (52/53-week years).
QUARTER_END_SLACK = timedelta(days=10)
_METRICS = {"revenue": "revenue", "eps": "eps_diluted"}  # Yahoo frame -> guidance metric
_QUARTERS = ("Q1", "Q2", "Q3", "Q4")


@dataclass(frozen=True)
class ConsensusRow:
    period: str  # 0q | +1q | 0y | +1y
    metric: str  # revenue | eps
    low: Decimal | None
    avg: Decimal | None
    high: Decimal | None
    analysts: int | None
    year_ago_revenue: Decimal | None  # the period's revenue anchor (EPS rows share it)


@dataclass(frozen=True)
class PlacedEstimate:
    metric: str  # a guidance metric: revenue | eps_diluted
    fiscal_year: int
    fiscal_period: str  # FY | Q1..Q4
    low: Decimal
    avg: Decimal | None
    high: Decimal
    analysts: int | None


def _number(value: object) -> Decimal | None:
    if value is None or pd.isna(value):  # type: ignore[call-overload]
        return None
    return Decimal(str(value))


def rows_from_frames(revenue: pd.DataFrame, earnings: pd.DataFrame) -> list[ConsensusRow]:
    """yfinance's `revenue_estimate` and `earnings_estimate` frames (indexed by period) as rows."""
    anchors = {str(p): _number(row.get("yearAgoRevenue")) for p, row in revenue.iterrows()}
    rows: list[ConsensusRow] = []
    for metric, frame in (("revenue", revenue), ("eps", earnings)):
        for period, row in frame.iterrows():
            analysts = _number(row.get("numberOfAnalysts"))
            rows.append(
                ConsensusRow(
                    str(period),
                    metric,
                    _number(row.get("low")),
                    _number(row.get("avg")),
                    _number(row.get("high")),
                    None if analysts is None else int(analysts),
                    anchors.get(str(period)),
                )
            )
    return rows


def _matches(actual: Decimal, year_ago: Decimal) -> bool:
    return actual != 0 and abs(year_ago - actual) / abs(actual) <= TOLERANCE


def _next_quarter(year: int, quarter: str) -> tuple[int, str]:
    i = _QUARTERS.index(quarter)
    return (year + 1, "Q1") if i == 3 else (year, _QUARTERS[i + 1])


def _ordinal(key: tuple[int, str]) -> int:
    return key[0] * 4 + _QUARTERS.index(key[1])


def place(
    rows: Sequence[ConsensusRow],
    annual_revenue: Mapping[int, Decimal],
    quarterly_revenue: Mapping[tuple[int, str], Decimal],
) -> list[PlacedEstimate]:
    """The rows on fiscal periods, by the stored revenue (annual by FY, quarterly by (FY, Qn))."""
    anchor = {r.period: r.year_ago_revenue for r in rows if r.metric == "revenue"}
    slots: dict[str, tuple[int, str]] = {}
    year_ago = anchor.get("0y")
    if year_ago is not None and annual_revenue:
        latest = max(annual_revenue)
        years = [
            fy for fy, v in annual_revenue.items() if latest - fy <= 1 and _matches(v, year_ago)
        ]
        if years:
            slots["0y"] = (max(years) + 1, "FY")
            slots["+1y"] = (max(years) + 2, "FY")
    year_ago = anchor.get("0q")
    if year_ago is not None and quarterly_revenue:
        latest_q = max(_ordinal(k) for k in quarterly_revenue)
        quarters = [
            k
            for k, v in quarterly_revenue.items()
            if latest_q - _ordinal(k) in (2, 3, 4) and _matches(v, year_ago)
        ]
        if quarters:
            fy, q = max(quarters, key=_ordinal)
            slots["0q"] = (fy + 1, q)
            slots["+1q"] = _next_quarter(fy + 1, q)
    placed: list[PlacedEstimate] = []
    for r in rows:
        slot = slots.get(r.period)
        if slot is None or r.low is None or r.high is None or r.low > r.high:
            continue
        placed.append(
            PlacedEstimate(_METRICS[r.metric], slot[0], slot[1], r.low, r.avg, r.high, r.analysts)
        )
    return placed


@dataclass(frozen=True)
class EpsHistoryRow:
    """One past quarter of Yahoo's earnings history: the EPS average before the report."""

    quarter_end: date  # Yahoo's calendar date of the quarter's end
    estimate: Decimal | None
    actual: Decimal | None


@dataclass(frozen=True)
class PlacedHistory:
    fiscal_year: int
    fiscal_period: str  # Q1..Q4
    estimate: Decimal
    quarter_end: date  # the fiscal quarter's own end


def history_from_frame(frame: pd.DataFrame) -> list[EpsHistoryRow]:
    """yfinance's `earnings_history` frame (indexed by quarter end) as rows, oldest first."""
    rows = [
        EpsHistoryRow(
            pd.Timestamp(str(quarter)).date(),
            _number(row.get("epsEstimate")),
            _number(row.get("epsActual")),
        )
        for quarter, row in frame.iterrows()
    ]
    return sorted(rows, key=lambda r: r.quarter_end)


def place_history(
    rows: Sequence[EpsHistoryRow],
    quarter_ends: Mapping[tuple[int, str], date],
    since: date,
) -> list[PlacedHistory]:
    """The past quarters ending on or after `since`, on the stored fiscal quarter whose end is
    nearest within `QUARTER_END_SLACK`; a row without an estimate or a nearby quarter is left out.
    By quarter end."""
    placed: list[PlacedHistory] = []
    for r in rows:
        if r.estimate is None or r.quarter_end < since:
            continue
        near = [
            (abs(end - r.quarter_end), key, end)
            for key, end in quarter_ends.items()
            if abs(end - r.quarter_end) <= QUARTER_END_SLACK
        ]
        if near:
            _, (fy, q), end = min(near)
            placed.append(PlacedHistory(fy, q, r.estimate, end))
    return sorted(placed, key=lambda p: p.quarter_end)
