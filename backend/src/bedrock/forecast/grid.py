"""The driver grid of a scenario: each driver's history and its resolved and own values per
forecast year (docs/erd/forecasting.md "API" -> DriverGridOut). Pure data."""

from dataclasses import dataclass
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
class DriverGrid:
    scenario_id: int
    history_years: list[int]
    forecast_years: list[int]
    rows: list[GridRow]
    warnings: list[str]
