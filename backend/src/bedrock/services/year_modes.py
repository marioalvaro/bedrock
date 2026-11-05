"""Year modes of a scenario (FR-FCST-13; docs/erd/forecasting.md "Year modes"): which forecast years
are set by quarter, the write rules that puts on a driver write, and the roll-up a by-quarter year
shows in the grid. `services/scenarios.py` runs the switch, the fill and the writes with these;
this module depends on no other service."""

from collections.abc import Collection, Iterable
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.forecast.engines.driver import FORECAST_HORIZON, DriverModel, forecast_quarters
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.grid import YearMode
from bedrock.forecast.history import ForecastHistory, ScenarioSettings, forecast_years
from bedrock.forecast.resolve import ResolvedDrivers
from bedrock.forecast.rollup import rollup
from bedrock.models.scenario import Scenario
from bedrock.repositories import scenarios as repo
from bedrock.services.errors import InvalidDrivers

__all__ = ["built_from_quarters", "check_mode_rules", "rollup_figures", "year_modes_of"]


def year_modes_of(session: Session, scenario: Scenario, history: ForecastHistory) -> list[YearMode]:
    """How each forecast year is set, in year order. A stored `quarterly` year that has left the
    quarterly span is `annual` (every caller reads the modes through here)."""
    years = forecast_years(history, FORECAST_HORIZON.years)
    span = {y for y, _ in forecast_quarters(history)}
    quarterly = repo.quarterly_years(session, scenario.id)
    return [
        YearMode(
            y,
            f"FY{y % 100:02d}E",
            "quarterly" if y in quarterly and y in span else "annual",
            y in span,
        )
        for y in years
    ]


def built_from_quarters(
    session: Session, scenario: Scenario, history: ForecastHistory
) -> list[int]:
    """The forecast years the scenario sets by quarter, in year order."""
    return [
        m.fiscal_year for m in year_modes_of(session, scenario, history) if m.mode == "quarterly"
    ]


def check_mode_rules(
    values: Iterable[tuple[int, Decimal | None]],
    quarters: Iterable[tuple[int, str, Decimal | None]],
    quarterly_years: Collection[int],
) -> None:
    """The write rules of one driver row: no annual value in a year set by quarter, no quarter
    value in a year set annually (a None is no value). A quarter of a year set by quarter may be
    left out or cleared: it then follows Base's quarter or the default, never the year's hidden
    annual value. Raises InvalidDrivers."""
    for year, value in values:
        if value is not None and year in quarterly_years:
            raise InvalidDrivers(f"FY{year} is set by quarter")
    for year, _, value in quarters:
        if value is not None and year not in quarterly_years:
            raise InvalidDrivers(f"FY{year} is set annually; switch it to by quarter first")


def rollup_figures(
    history: ForecastHistory,
    settings: ScenarioSettings,
    resolved: ResolvedDrivers,
    years: Collection[int],
) -> dict[tuple[str, int], Decimal | None]:
    """The annual figures of the years set by quarter (`forecast/rollup.py`), from the case's
    forecast; none when no year is set by quarter or the model cannot run (the grid keeps its
    warnings, the Forecast tab says why)."""
    if not years:
        return {}
    try:
        statements = DriverModel().run(history, resolved, FORECAST_HORIZON, settings)
    except ForecastUnavailable:
        return {}
    return rollup(history, settings, statements, resolved, sorted(years))
