"""The driver grid of a scenario case: each driver's history and its resolved and own values per
forecast year (docs/erd/forecasting.md "API" -> DriverGridOut). Pure data."""

from dataclasses import dataclass, field
from decimal import Decimal

from bedrock.forecast.drivers import DriverKind, Unit
from bedrock.forecast.resolve import Source


@dataclass(frozen=True)
class GridRow:
    """One driver of the grid. `history` is aligned with the grid's history years; `values`,
    `sources` and `own` with its forecast years. A value held flat is None with source
    `default`; a required driver nothing sets is None with source None. `own` is the scenario's
    stored value or offset (as stored), `kind` the stored kind of its own rows."""

    code: str
    label: str
    group: str
    unit: Unit
    history: list[Decimal | None]
    values: list[Decimal | None]
    sources: list[Source | None]
    own: list[Decimal | None]
    kind: DriverKind | None


@dataclass(frozen=True)
class GridPeriod:
    """A column of the grid: a fiscal year (`FY`) or a quarter, with its label (`FY26E`,
    `Q1 FY25A`)."""

    fiscal_year: int
    fiscal_period: str
    label: str


@dataclass(frozen=True)
class DriverGrid:
    """`history_years` / `forecast_years` are always the annual years; for the annual grid
    `history_periods` / `forecast_periods` mirror them, for the quarterly grid (`freq`) they are
    the actual quarters and the span's quarters that the rows' lists are aligned with."""

    scenario_id: int
    case: str
    history_years: list[int]
    forecast_years: list[int]
    rows: list[GridRow]
    warnings: list[str]
    freq: str = "annual"
    history_periods: list[GridPeriod] = field(default_factory=list)
    forecast_periods: list[GridPeriod] = field(default_factory=list)
