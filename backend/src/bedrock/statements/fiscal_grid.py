"""Fiscal periods from one fiscal-year-end date. Pure.

The manual-import template does not ask for dates per column: a company gives the date its annual
period ends, and every fiscal year and quarter follows from it. A year end on the last day of its
month keeps month ends in every year; any other day repeats its day of the month (clamped to the
month's length), which is close to a 52/53-week year's real dates. A column that needs exact
dates can override them in the file.
"""

import calendar
from collections.abc import Iterable
from datetime import date, timedelta

from bedrock.statements.periods import Period

PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4")
GRID_YEARS = 20


def period_dates(fiscal_year_end: date, fiscal_year: int, fiscal_period: str) -> tuple[date, date]:
    """The start and end of a fiscal period. `fiscal_year_end` is the end of any fiscal year; the
    fiscal year is the calendar year it ends in, except that a year ending January 1-7 belongs to
    the year before (`periods.fiscal_year_of`). Raises ValueError for an unknown period."""
    if fiscal_period not in PERIODS:
        raise ValueError(f"Unknown fiscal period '{fiscal_period}'")
    shift = 1 if fiscal_year_end.month == 1 and fiscal_year_end.day <= 7 else 0
    month_end = fiscal_year_end.day == calendar.monthrange(*_ym(fiscal_year_end))[1]

    def end_in(year: int, month: int) -> date:
        year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
        last = calendar.monthrange(year, month)[1]
        return date(year, month, last if month_end else min(fiscal_year_end.day, last))

    year_end = end_in(fiscal_year + shift, fiscal_year_end.month)
    year_start = end_in(fiscal_year - 1 + shift, fiscal_year_end.month) + timedelta(days=1)
    if fiscal_period == "FY":
        return year_start, year_end
    quarter = int(fiscal_period[1])
    end = end_in(fiscal_year + shift, fiscal_year_end.month - 3 * (4 - quarter))
    if quarter == 1:
        return year_start, end
    previous = end_in(fiscal_year + shift, fiscal_year_end.month - 3 * (4 - quarter + 1))
    return previous + timedelta(days=1), end


def period_grid(fiscal_year_end: date, last_year: int, years: int = GRID_YEARS) -> list[Period]:
    """`years` fiscal years ending at `last_year`, oldest first, each as FY, Q1, Q2, Q3, Q4."""
    grid: list[Period] = []
    for year in range(last_year - years + 1, last_year + 1):
        label = f"FY{year % 100:02d}"
        for period in PERIODS:
            start, end = period_dates(fiscal_year_end, year, period)
            key = f"FY{year}" if period == "FY" else f"FY{year}{period}"
            grid.append(
                Period(
                    key,
                    label if period == "FY" else f"{period} {label}",
                    year,
                    period,
                    start,
                    end,
                )
            )
    return grid


def annual_then_quarterly(periods: Iterable[Period]) -> list[Period]:
    """The template's column order: every fiscal year first, then every quarter (Q1..Q4 of a year
    in turn), each oldest first, so that a whole row of annual or of quarterly values pastes in
    one block."""
    return sorted(
        periods,
        key=lambda p: (p.fiscal_period != "FY", p.fiscal_year, PERIODS.index(p.fiscal_period)),
    )


def _ym(day: date) -> tuple[int, int]:
    return day.year, day.month
