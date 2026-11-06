"""The STL decomposition of a quarterly income-statement or cash-flow line (FR-FCST-08; docs/erd/
forecasting.md "Statistical engines (M6)" → API → seasonality). Imports no other service."""

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from sqlalchemy.orm import Session

from bedrock.forecast.engines.stl import INDEX_QUARTERS, MIN_QUARTERS, decompose, seasonal_index
from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.interface import quarter_values
from bedrock.models.company import Company
from bedrock.services.errors import InvalidSeasonality
from bedrock.services.statements import statement_tables
from bedrock.statements.build import Freq, Row, StatementTable
from bedrock.statements.periods import Period

__all__ = ["DEFAULT_LINE", "Factor", "Seasonality", "SeasonalLine", "decomposition"]

DEFAULT_LINE = "revenue"
STATEMENTS = ("IS", "CF")


@dataclass(frozen=True)
class SeasonalLine:
    code: str
    label: str


@dataclass(frozen=True)
class Factor:
    fiscal_period: str
    value: float  # the seasonal index, in the line's unit
    pct: float | None  # value ÷ the mean trend of the last 12 quarters; None when that is 0


@dataclass(frozen=True)
class Seasonality:
    code: str
    label: str
    lines: list[SeasonalLine]
    periods: list[Period]
    observed: list[float]
    trend: list[float]
    seasonal: list[float]
    residual: list[float]
    factors: list[Factor]
    strength: float


def decomposition(session: Session, company: Company, code: str = DEFAULT_LINE) -> Seasonality:
    """The line's STL components over its latest consecutive run of quarters, its seasonal factors
    and strength, with the lines that can be decomposed. Raises InvalidSeasonality."""
    wanted: list[tuple[str, Freq]] = [(s, "quarterly") for s in STATEMENTS]
    tables = statement_tables(session, company, wanted, "normalized")
    statements = [tables[key] for key in wanted]
    if not statements[0].periods:
        raise InvalidSeasonality("No quarterly history")
    runs = {row.code: (row, _run(table, row)) for table in statements for row in _lines(table)}
    available = [
        SeasonalLine(c, row.label) for c, (row, run) in runs.items() if len(run[1]) >= MIN_QUARTERS
    ]
    if code not in runs:
        raise InvalidSeasonality(f"Unknown line {code}")
    row, (periods, values) = runs[code]
    if len(values) < MIN_QUARTERS:
        raise InvalidSeasonality(f"{row.label} has fewer than {MIN_QUARTERS} consecutive quarters")
    start = periods[0]
    series = quarter_values(start.fiscal_year, int(start.fiscal_period[1]), values)
    try:
        parts = decompose(series)
        index = seasonal_index(series)
    except EngineFailed as exc:
        raise InvalidSeasonality(exc.message) from exc
    level = float(np.mean(parts.trend[-INDEX_QUARTERS:]))
    factors = [Factor(q, v, None if level == 0 else v / level) for q, v in index.items()]
    return Seasonality(
        code,
        row.label,
        available,
        periods,
        parts.observed,
        parts.trend,
        parts.seasonal,
        parts.residual,
        factors,
        parts.strength,
    )


def _lines(table: StatementTable) -> list[Row]:
    """The canonical lines of the table (a custom line has no canonical code to decompose)."""
    return [r for r in table.rows if not r.custom]


def _run(table: StatementTable, row: Row) -> tuple[list[Period], list[float]]:
    """The row's latest run of consecutive non-null quarters ending at the table's last quarter."""
    periods: list[Period] = []
    values: list[float] = []
    for period, value in zip(reversed(table.periods), reversed(row.values), strict=True):
        if value is None:
            break
        periods.append(period)
        values.append(float(Decimal(value)))
    return periods[::-1], values[::-1]
