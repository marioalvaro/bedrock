"""Point-in-time backtest runs (docs/erd/accountability.md "Backtest"): where they start and one
run of one engine from a history cut at the origin. Pure: the engines' `fit` is injected."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from bedrock.backtest.scoring import SCORED_CODES
from bedrock.backtest.snapshot import ValueRow, run_meta, value_rows
from bedrock.forecast.drivers import SEASONAL
from bedrock.forecast.engine_defaults import EngineCode, EngineRow, Fit, engine_defaults
from bedrock.forecast.engines.driver import FORECAST_HORIZON, DriverModel
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    default_drivers,
    forecast_years,
    scenario_drivers,
)
from bedrock.forecast.resolve import resolve_drivers

BACKTEST_ORIGINS = 10
SETTINGS = ScenarioSettings("growth")


@dataclass(frozen=True)
class MethodRun:
    rows: list[ValueRow]  # empty when the run has an `error`
    meta: str  # `forecast_run.engines_json`
    error: str | None


def origins(ten_k_dates: Sequence[date]) -> list[date]:
    """The last BACKTEST_ORIGINS distinct dates before the newest (which has no actuals after it),
    oldest first."""
    return sorted(set(ten_k_dates))[:-1][-BACKTEST_ORIGINS:]


def run_method(history: ForecastHistory, method: EngineCode, fit: Fit) -> MethodRun:
    """The growth-method forecast with every driver on `method` and no manual input. A forecast
    the history cannot support is the run's `error`; a failed integrity check still raises."""
    engines: Mapping[str, EngineRow] = {}
    try:
        years = forecast_years(history, FORECAST_HORIZON.years)
        defaults = engine_defaults(history, SETTINGS, _choices(history, method), years, fit)
        engines = defaults.rows
        resolved = resolve_drivers(
            [],
            [],
            default_drivers(history, SETTINGS),
            years,
            is_base=True,
            quarterly_years=frozenset(),
            engine_values=defaults.values,
            seasonal=defaults.seasonal,
        )
        statements = DriverModel().run(history, resolved, FORECAST_HORIZON, SETTINGS)
    except ForecastUnavailable as unavailable:
        return MethodRun([], run_meta(SETTINGS, engines, ()), unavailable.detail)
    warnings = (*defaults.warnings, *resolved.warnings, *statements.warnings)
    return MethodRun(
        value_rows(statements, resolved, engines, SCORED_CODES),
        run_meta(SETTINGS, engines, warnings),
        None,
    )


def _choices(history: ForecastHistory, method: EngineCode) -> dict[str, EngineCode]:
    """`method` for each driver of the method; STL applies only to a seasonal driver."""
    return {
        d.code: "auto" if method == "stl" and d.code not in SEASONAL else method
        for d in scenario_drivers(history, SETTINGS)
    }
