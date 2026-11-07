"""Engine choices of a scenario and the engine defaults they set (FR-FCST-07, -08, -11; docs/erd/
forecasting.md "Statistical engines (M6)" → Service). Imports no other service; `services/
scenarios.py` calls it."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, cast

import pandas as pd
from sqlalchemy.orm import Session

from bedrock.forecast import registry
from bedrock.forecast.drivers import SEASONAL, Unit
from bedrock.forecast.engine_defaults import (
    ENGINE_CODES,
    DriverEngines,
    EngineCode,
    EngineDefaults,
    UsedEngine,
    driver_engines,
    engine_defaults,
)
from bedrock.forecast.history import ForecastHistory, ScenarioSettings, scenario_drivers
from bedrock.forecast.interface import ForecastResult, SeriesInput
from bedrock.models.scenario import Scenario
from bedrock.repositories import engines as repo
from bedrock.services.errors import InvalidEngineChoice

__all__ = [
    "EngineChoiceRow",
    "EngineChoices",
    "engine_choices",
    "engine_choices_view",
    "engine_defaults_for",
    "fit_cache_clear",
    "fit_cache_info",
    "inspect_driver",
    "memo_fit",
    "put_engine_choices",
]

FIT_MEMO_SIZE = 4096


@dataclass(frozen=True)
class EngineChoiceRow:
    """One driver of the scenario's method with its engine choice and what produced its default."""

    driver_code: str
    label: str
    group: str
    unit: Unit
    engine: EngineCode
    used: UsedEngine | None
    note: str | None
    seasonal: bool


@dataclass(frozen=True)
class EngineChoices:
    scenario_id: int
    rows: list[EngineChoiceRow]


@lru_cache(maxsize=FIT_MEMO_SIZE)
def _fit(
    code: str, freq: str, first: str, values: tuple[float, ...], horizon: int
) -> ForecastResult:
    index = pd.period_range(first, periods=len(values), freq=freq)
    return registry.fit(code, SeriesInput(pd.Series(values, index=index, dtype=float)), horizon)


def memo_fit(code: str, data: SeriesInput, horizon: int) -> ForecastResult:
    """`registry.fit`, memoized per worker process on the engine, the series' index and values and
    the horizon: a refresh or an adjustment changes the values, hence the key, so nothing is
    invalidated by hand. The result is shared: callers must not mutate it."""
    index = cast("pd.PeriodIndex", data.values.index)
    return _fit(
        code,
        str(index.freqstr),
        str(index[0]),
        tuple(float(v) for v in data.values),
        horizon,
    )


def fit_cache_info() -> Any:
    """The memo's hits, misses and size (`functools` cache info)."""
    return _fit.cache_info()


def fit_cache_clear() -> None:
    _fit.cache_clear()


def engine_choices(session: Session, scenario_id: int) -> dict[str, EngineCode]:
    """The scenario's stored choices by driver code (a missing driver is `auto`). Stale rows, for
    drivers the method no longer lists, are included: the defaults ignore them."""
    return {
        r.driver_code: cast(EngineCode, r.engine_code) for r in repo.list_for(session, scenario_id)
    }


def engine_defaults_for(
    history: ForecastHistory,
    settings: ScenarioSettings,
    choices: Mapping[str, EngineCode],
    years: Sequence[int],
) -> EngineDefaults:
    """The pure `engine_defaults` with the memoized `fit`."""
    return engine_defaults(history, settings, choices, years, fit=memo_fit)


def engine_choices_view(
    session: Session,
    scenario: Scenario,
    history: ForecastHistory,
    settings: ScenarioSettings,
    years: Sequence[int],
) -> EngineChoices:
    """The drivers of the scenario's method in catalog order with their choice and what produced
    the default."""
    choices = engine_choices(session, scenario.id)
    defaults = engine_defaults_for(history, settings, choices, years)
    rows = []
    for d in scenario_drivers(history, settings):
        row = defaults.rows[d.code]
        rows.append(
            EngineChoiceRow(
                d.code, d.label, d.group, d.unit, row.choice, row.used, row.note, row.seasonal
            )
        )
    return EngineChoices(scenario.id, rows)


def put_engine_choices(
    session: Session,
    scenario: Scenario,
    history: ForecastHistory,
    settings: ScenarioSettings,
    rows: Sequence[tuple[str, str]],
    stamp: datetime,
) -> None:
    """Checks every (driver code, engine) row, then writes them in one transaction: `auto`
    deletes the driver's row. Raises InvalidEngineChoice (nothing written)."""
    drivers = {d.code for d in scenario_drivers(history, settings)}
    method = settings.revenue_method
    seen: set[str] = set()
    for code, engine in rows:
        if engine not in ENGINE_CODES:
            raise InvalidEngineChoice(f"{engine} is not an engine")
        if code not in drivers:
            raise InvalidEngineChoice(f"{code} is not a driver of the {method} method")
        if code in seen:
            raise InvalidEngineChoice(f"{code} is given twice")
        seen.add(code)
        if engine == "stl" and code not in SEASONAL:
            raise InvalidEngineChoice(f"STL applies to ratio and days drivers only: {code}")
    repo.put(session, scenario.id, {c: None if e == "auto" else e for c, e in rows}, stamp)
    session.commit()


def inspect_driver(
    session: Session,
    scenario: Scenario,
    history: ForecastHistory,
    settings: ScenarioSettings,
    code: str,
    years: Sequence[int],
) -> DriverEngines:
    """One driver's engines on the whole run (see `engine_defaults.driver_engines`). Raises
    InvalidEngineChoice for a code outside the scenario's method."""
    if code not in {d.code for d in scenario_drivers(history, settings)}:
        raise InvalidEngineChoice(f"{code} is not a driver of the {settings.revenue_method} method")
    choice = engine_choices(session, scenario.id).get(code, "auto")
    return driver_engines(history, settings, code, choice, years, fit=memo_fit)
