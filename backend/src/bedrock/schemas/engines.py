from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from bedrock.forecast.drivers import Unit
from bedrock.forecast.engine_defaults import Band, EngineFit
from bedrock.forecast.resolve import Source
from bedrock.services.engines import EngineChoices
from bedrock.services.scenarios import CaseDriverEngines

EngineName = Literal["auto", "mean", "arima", "ets", "blend", "stl"]
UsedName = Literal["mean", "arima", "ets", "blend"]


class EngineRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_code: str
    engine: EngineName


class EngineChoicesIn(BaseModel):
    """Each row sets one driver's engine (`auto` deletes the choice); drivers not listed are
    untouched."""

    model_config = ConfigDict(extra="forbid")

    rows: list[EngineRowIn]

    def to_input(self) -> list[tuple[str, str]]:
        return [(r.driver_code, r.engine) for r in self.rows]


class EngineRowOut(BaseModel):
    """`engine` is the choice (`auto` when none is stored), `used` what produced the default (null
    for a driver with no numeric default), `seasonal` whether `stl` is allowed."""

    driver_code: str
    label: str
    group: str
    unit: Unit
    engine: EngineName
    used: UsedName | None
    note: str | None
    seasonal: bool


class EngineChoicesOut(BaseModel):
    scenario_id: int
    rows: list[EngineRowOut]

    @classmethod
    def from_view(cls, view: EngineChoices) -> "EngineChoicesOut":
        return cls(
            scenario_id=view.scenario_id,
            rows=[EngineRowOut.model_validate(r, from_attributes=True) for r in view.rows],
        )


class HistoryPeriodOut(BaseModel):
    fiscal_year: int
    label: str


class EngineFitOut(BaseModel):
    """One engine's forecast on the whole run: the point and the 90% / 50% quantiles per forecast
    year (empty with `error` set when it could not fit)."""

    code: str
    label: str
    values: list[Decimal]
    p05: list[Decimal]
    p25: list[Decimal]
    p75: list[Decimal]
    p95: list[Decimal]
    holdout_mae: Decimal | None
    meta: dict[str, Any]
    error: str | None

    @classmethod
    def from_fit(cls, fit: EngineFit, years: list[int]) -> "EngineFitOut":
        shown = [y for y in years if y in fit.values]
        band: dict[int, Band] = dict(fit.band)
        return cls(
            code=fit.code,
            label=fit.label,
            values=[fit.values[y] for y in shown],
            p05=[band[y].p05 for y in shown],
            p25=[band[y].p25 for y in shown],
            p75=[band[y].p75 for y in shown],
            p95=[band[y].p95 for y in shown],
            holdout_mae=fit.holdout_mae,
            meta=dict(fit.meta),
            error=fit.error,
        )


class SeasonalIndexOut(BaseModel):
    fiscal_period: Literal["Q1", "Q2", "Q3", "Q4"]
    value: Decimal


class DriverEnginesOut(BaseModel):
    """The driver's whole consecutive run (`history`), the case's resolved values and sources per
    forecast year, each Tier 2 engine fit on the run, the M4 mean and the seasonal index."""

    driver_code: str
    label: str
    unit: Unit
    engine: EngineName
    used: UsedName | None
    note: str | None
    history_periods: list[HistoryPeriodOut]
    history: list[Decimal]
    forecast_years: list[int]
    forecast_labels: list[str]
    values: list[Decimal | None]
    sources: list[Source | None]
    engines: list[EngineFitOut]
    mean: Decimal | None
    seasonal: list[SeasonalIndexOut] | None

    @classmethod
    def from_view(cls, code: str, view: CaseDriverEngines) -> "DriverEnginesOut":
        inspection = view.inspection
        return cls(
            driver_code=code,
            label=view.label,
            unit=view.unit,
            engine=inspection.choice,
            used=inspection.used,
            note=inspection.note,
            history_periods=[
                HistoryPeriodOut(fiscal_year=y, label=f"FY{y % 100:02d}A")
                for y, _ in inspection.run
            ],
            history=[v for _, v in inspection.run],
            forecast_years=view.forecast_years,
            forecast_labels=[f"FY{y % 100:02d}E" for y in view.forecast_years],
            values=view.values,
            sources=view.sources,
            engines=[EngineFitOut.from_fit(e, view.forecast_years) for e in inspection.engines],
            mean=inspection.mean,
            seasonal=None
            if inspection.seasonal is None
            else [
                SeasonalIndexOut(fiscal_period=q, value=v) for q, v in inspection.seasonal.items()
            ],
        )
