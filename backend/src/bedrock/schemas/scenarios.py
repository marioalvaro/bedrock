from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bedrock.forecast.drivers import DriverKind, RevenueMethod, Unit
from bedrock.forecast.resolve import Source
from bedrock.models.scenario import Case, Scenario
from bedrock.services.scenarios import (
    DriverGrid,
    DriverImportResult,
    DriverRowInput,
    GridPeriod,
    SettingsInput,
    YearMode,
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
    """A POST: the settings not given are the default scenario's."""

    name: str


class ScenarioOut(BaseModel):
    id: int
    name: str
    is_default: bool
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
    nothing sets is null with source null. `own` is the case's stored value, or offset when
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
    rollup: list[Decimal | None]  # aligned with `forecast_years`; null for a year set annually


class YearModeOut(BaseModel):
    """How a forecast year is set: `annual` or `quarterly` (by quarter). `in_span`: the year is
    built from quarters and can be switched; later years are always annual."""

    fiscal_year: int
    label: str
    mode: Literal["annual", "quarterly"]
    in_span: bool

    @classmethod
    def from_mode(cls, mode: YearMode) -> "YearModeOut":
        return cls.model_validate(mode, from_attributes=True)


class YearModesOut(BaseModel):
    years: list[YearModeOut]

    @classmethod
    def from_modes(cls, modes: list[YearMode]) -> "YearModesOut":
        return cls(years=[YearModeOut.from_mode(m) for m in modes])


class YearModeIn(BaseModel):
    mode: Literal["annual", "quarterly"]


class GridPeriodOut(BaseModel):
    """A column of the grid: a fiscal year (`FY`) or a quarter (`Q1`..`Q4`) with its label."""

    fiscal_year: int
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4"]
    label: str

    @classmethod
    def from_period(cls, period: GridPeriod) -> "GridPeriodOut":
        return cls.model_validate(period, from_attributes=True)


class DriverGridOut(BaseModel):
    """`history_years` / `forecast_years` are the annual years in both frequencies; the rows'
    `history` is aligned with `history_periods` and `values` / `sources` / `own` with
    `forecast_periods` (the years for `annual`, the actual and the span's quarters for
    `quarterly`)."""

    scenario_id: int
    case: Case
    freq: Literal["annual", "quarterly"]
    history_years: list[int]
    forecast_years: list[int]
    history_periods: list[GridPeriodOut]
    forecast_periods: list[GridPeriodOut]
    rows: list[DriverRowOut]
    warnings: list[str]
    year_modes: list[YearModeOut]

    @classmethod
    def from_grid(cls, grid: DriverGrid) -> "DriverGridOut":
        return cls(
            scenario_id=grid.scenario_id,
            case=grid.case,
            freq=grid.freq,
            history_years=grid.history_years,
            forecast_years=grid.forecast_years,
            history_periods=[GridPeriodOut.from_period(p) for p in grid.history_periods],
            forecast_periods=[GridPeriodOut.from_period(p) for p in grid.forecast_periods],
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
                    rollup=r.rollup,
                )
                for r in grid.rows
            ],
            warnings=grid.warnings,
            year_modes=[YearModeOut.from_mode(m) for m in grid.year_modes],
        )


class DriverYearIn(BaseModel):
    fiscal_year: int
    # FY in an annual row, Q1..Q4 in a quarterly one (anything else is a 422)
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4"] = "FY"
    value: Decimal | None  # null: no stored value for the period


class DriverRowIn(BaseModel):
    driver_code: str
    kind: DriverKind
    freq: Literal["annual", "quarterly"] = "annual"
    values: list[DriverYearIn]


class DriversIn(BaseModel):
    """Each row replaces the stored rows of its driver of its frequency in the case."""

    rows: list[DriverRowIn]

    def to_input(self) -> list[DriverRowInput]:
        return [
            DriverRowInput(
                r.driver_code,
                r.kind,
                [(v.fiscal_year, v.value) for v in r.values if v.fiscal_period == "FY"],
                r.freq,
                [
                    (v.fiscal_year, v.fiscal_period, v.value)
                    for v in r.values
                    if v.fiscal_period != "FY"
                ],
            )
            for r in self.rows
        ]


class DriverChangeOut(BaseModel):
    """A stored row a driver file changes: its kind and value before and after (null: none)."""

    driver_code: str
    fiscal_year: int
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4"]
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
                    fiscal_period=c.fiscal_period,
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
