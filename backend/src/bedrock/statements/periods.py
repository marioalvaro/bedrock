"""Fiscal calendar and period identities, derived from the dates of mapped flow facts. Pure.

`fy`/`fp` from EDGAR describe filings, not periods, so nothing here reads them: fiscal years and
quarters are found from the `start`/`end` of the facts themselves.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

FY_DAYS = (350, 380)  # a mapped flow fact this long is a fiscal year
QUARTER_END_DAYS = (70, 300)  # a Q1..Q3 end lies this far after the year start
START_TOLERANCE = timedelta(days=7)


@dataclass(frozen=True)
class Period:
    key: str  # FY2024, FY2024Q3, TTM-FY2024Q3
    label: str  # FY24, Q3 FY24, TTM Q3 FY24
    fiscal_year: int
    fiscal_period: str  # FY, Q1..Q4 (a TTM period carries the quarter it ends at)
    start: date
    end: date


@dataclass(frozen=True)
class FiscalYear:
    fiscal_year: int
    start: date
    end: date | None  # None: the year is still open (no 10-K yet)
    quarter_ends: tuple[date, ...]  # Q1..Q3 ends; empty when the year's quarters are unknown


@dataclass(frozen=True)
class Calendar:
    years: tuple[FiscalYear, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TtmWindow:
    period: Period
    quarters: tuple[Period, ...]  # the four discrete quarters it sums, oldest first


def fiscal_year_of(end: date) -> int:
    """The calendar year the fiscal year ends in; a 53-week year ending Jan 1-7 belongs to
    the year before."""
    return end.year - 1 if end.month == 1 and end.day <= 7 else end.year


def fiscal_calendar(frame: pd.DataFrame) -> Calendar:
    flows = sorted(
        {
            (start, end)
            for start, end, kind in zip(
                frame["period_start"], frame["period_end"], frame["kind"], strict=True
            )
            if kind == "flow" and not pd.isna(start)
        }
    )
    year_spans: dict[int, tuple[date, date]] = {}
    warnings: list[str] = []
    for start, end in flows:
        if FY_DAYS[0] <= (end - start).days <= FY_DAYS[1]:
            fy = fiscal_year_of(end)
            if fy in year_spans:
                warnings.append(
                    f"FY{fy}: more than one fiscal-year period; kept the one ending {end}"
                )
            year_spans[fy] = (start, end)

    years: list[FiscalYear] = []
    for fy in sorted(year_spans):
        start, end = year_spans[fy]
        ends = _quarter_ends(flows, start)
        if len(ends) != 3:
            warnings.append(
                f"FY{fy}: expected 3 quarter ends, found {len(ends)}; quarters left empty"
            )
            ends = []
        years.append(FiscalYear(fy, start, end, tuple(ends)))

    if years:
        last = years[-1]
        assert last.end is not None
        next_start = last.end + timedelta(days=1)
        ends = _quarter_ends(flows, next_start)
        if 1 <= len(ends) <= 3:
            years.append(FiscalYear(last.fiscal_year + 1, next_start, None, tuple(ends)))
        elif len(ends) > 3:
            warnings.append(f"FY{last.fiscal_year + 1}: more than 3 quarter ends; left out")
    return Calendar(tuple(years), tuple(warnings))


def _quarter_ends(flows: list[tuple[date, date]], year_start: date) -> list[date]:
    return sorted(
        {
            end
            for start, end in flows
            if abs(start - year_start) <= START_TOLERANCE
            and QUARTER_END_DAYS[0] <= (end - year_start).days <= QUARTER_END_DAYS[1]
        }
    )


def annual_periods(calendar: Calendar) -> list[Period]:
    return [
        Period(f"FY{y.fiscal_year}", _fy_label(y.fiscal_year), y.fiscal_year, "FY", y.start, y.end)
        for y in calendar.years
        if y.end is not None
    ]


def quarterly_periods(calendar: Calendar) -> list[Period]:
    periods: list[Period] = []
    for y in calendar.years:
        ends = y.quarter_ends + ((y.end,) if y.end is not None and y.quarter_ends else ())
        start = y.start
        for n, end in enumerate(ends, start=1):
            periods.append(
                Period(
                    f"FY{y.fiscal_year}Q{n}",
                    f"Q{n} {_fy_label(y.fiscal_year)}",
                    y.fiscal_year,
                    f"Q{n}",
                    start,
                    end,
                )
            )
            start = end + timedelta(days=1)
    return periods


def ttm_windows(calendar: Calendar) -> list[TtmWindow]:
    """A TTM period at every quarter that has three consecutive predecessors."""
    by_slot = {
        p.fiscal_year * 4 + int(p.fiscal_period[1]) - 1: p for p in quarterly_periods(calendar)
    }
    windows = []
    for slot, last in sorted(by_slot.items()):
        quarters = [by_slot.get(s) for s in range(slot - 3, slot + 1)]
        if any(q is None for q in quarters):
            continue
        window = tuple(q for q in quarters if q is not None)
        period = Period(
            f"TTM-{last.key}",
            f"TTM {last.label}",
            last.fiscal_year,
            last.fiscal_period,
            window[0].start,
            last.end,
        )
        windows.append(TtmWindow(period, window))
    return windows


def _fy_label(fiscal_year: int) -> str:
    return f"FY{fiscal_year % 100:02d}"
