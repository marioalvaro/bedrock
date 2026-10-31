from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bedrock.forecast.drivers import DriverKind, RevenueMethod, Unit
from bedrock.forecast.resolve import Source
from bedrock.models.scenario import Scenario
from bedrock.services.scenarios import (
    DriverGrid,
    DriverImportResult,
    DriverRowInput,
    SettingsInput,
)


class ScenarioSettingsIn(BaseModel):
    """A PUT: every field optional, an absent one is left as it is. An unknown field is a 422,
    so a client still sending the removed horizon fields learns it at once."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    revenue_method: RevenueMethod | None = None
    segment_dimension: Literal["business", "geo"] | None = None
    volume_kpi: str | None = None  # a KPI code of unit count
    price_kpi: str | None = None  # a KPI code of unit USD_per_unit

    def to_input(self) -> SettingsInput:
        return SettingsInput(**self.model_dump())


class ScenarioIn(ScenarioSettingsIn):
    """A POST: the settings not given are Base's."""

    name: str


class ScenarioOut(BaseModel):
    id: int
    name: str
    is_default: bool
    base_id: int | None
    revenue_method: RevenueMethod
    segment_dimension: Literal["business", "geo"] | None
    volume_kpi: str | None
    price_kpi: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, scenario: Scenario) -> "ScenarioOut":
        return cls.model_validate(scenario, from_attributes=True)


class DriverRowOut(BaseModel):
    """`history` is aligned with the grid's `history_years`; `values`, `sources` and `own` with
    its `forecast_years`. A value held flat is null with source `default`; a required driver
    nothing sets is null with source null. `own` is the scenario's stored value, or offset when
    `kind` is `offset`."""

    code: str
    label: str
    group: str
    unit: Unit
    history: list[Decimal | None]
    values: list[Decimal | None]
    sources: list[Source | None]
    own: list[Decimal | None]
    kind: DriverKind | None


class DriverGridOut(BaseModel):
    scenario_id: int
    history_years: list[int]
    forecast_years: list[int]
    rows: list[DriverRowOut]
    warnings: list[str]

    @classmethod
    def from_grid(cls, grid: DriverGrid) -> "DriverGridOut":
        return cls(
            scenario_id=grid.scenario_id,
            history_years=grid.history_years,
            forecast_years=grid.forecast_years,
            rows=[
                DriverRowOut(
                    code=r.code,
                    label=r.label,
                    group=r.group,
                    unit=r.unit,
                    history=r.history,
                    values=r.values,
                    sources=r.sources,
                    own=r.own,
                    kind=r.kind,
                )
                for r in grid.rows
            ],
            warnings=grid.warnings,
        )


class DriverYearIn(BaseModel):
    fiscal_year: int
    value: Decimal | None  # null: no stored value for the year


class DriverRowIn(BaseModel):
    driver_code: str
    kind: DriverKind
    values: list[DriverYearIn]


class DriversIn(BaseModel):
    """Each row replaces every stored row of its driver in the scenario."""

    rows: list[DriverRowIn]

    def to_input(self) -> list[DriverRowInput]:
        return [
            DriverRowInput(r.driver_code, r.kind, [(v.fiscal_year, v.value) for v in r.values])
            for r in self.rows
        ]


class DriverChangeOut(BaseModel):
    """A stored row a driver file changes: its kind and value before and after (null: none)."""

    driver_code: str
    fiscal_year: int
    old: Decimal | None
    new: Decimal | None
    old_kind: DriverKind | None
    new_kind: DriverKind | None


class DriverImportOut(BaseModel):
    """A driver file's changes; `grid` is the new grid after a confirmed import, null for a dry
    run."""

    dry_run: bool
    changes: list[DriverChangeOut]
    grid: DriverGridOut | None

    @classmethod
    def from_result(cls, result: DriverImportResult, dry_run: bool) -> "DriverImportOut":
        return cls(
            dry_run=dry_run,
            changes=[
                DriverChangeOut(
                    driver_code=c.driver_code,
                    fiscal_year=c.fiscal_year,
                    old=c.old,
                    new=c.new,
                    old_kind=c.old_kind,
                    new_kind=c.new_kind,
                )
                for c in result.changes
            ],
            grid=None if result.grid is None else DriverGridOut.from_grid(result.grid),
        )


class DriverFileIssueOut(BaseModel):
    """An error of a driver file; `row` and `column` (a letter) say where, null for the file."""

    row: int | None
    column: str | None
    message: str


class DriverFileErrorsOut(BaseModel):
    """The 422 body of a driver file with errors."""

    detail: str
    errors: list[DriverFileIssueOut]
