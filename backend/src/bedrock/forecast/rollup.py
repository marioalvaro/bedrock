"""The annual figure of a forecast year built from its quarters (docs/erd/forecasting.md "Year
modes" → Roll-up). Pure."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from bedrock.forecast.drivers import QUARTERS, DriverDef, SeriesGrowth
from bedrock.forecast.engines.driver import ForecastStatements
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    annual_driver_values,
    scenario_drivers,
)
from bedrock.forecast.resolve import ResolvedDrivers
from bedrock.statements.build import extend_table
from bedrock.statements.view import select_periods


def rollup(
    history: ForecastHistory,
    settings: ScenarioSettings,
    statements: ForecastStatements,
    resolved: ResolvedDrivers,
    years: Sequence[int],
) -> dict[tuple[str, int], Decimal | None]:
    """Each driver of the scenario for each of `years` the forecast covers: the driver's history
    rule on the forecast's annual statements (placed after the actual years, so growth and mean
    debt reach back into them), None where an input is missing. Two kinds have no statement rule:
    a segment or KPI growth, whose annual series the forecast does not carry, is the year's
    driver while its four quarters agree with it and None once one differs; `min_cash`, a floor,
    is the last quarter's. A year the statements do not cover is left out."""
    annual = statements.annual()
    covered = [y for y in years if y in {p.fiscal_year for p in annual}]
    if not covered:
        return {}
    first = annual[0].fiscal_year
    tables = {}
    for statement, table in history.annual.items():
        before = [p.key for p in table.periods if p.fiscal_year < first]
        tables[statement] = extend_table(select_periods(table, before), annual, statements.values)
    values = annual_driver_values(replace(history, annual=tables), settings, covered)
    found: dict[tuple[str, int], Decimal | None] = {}
    for d in scenario_drivers(history, settings):
        for year in covered:
            found[(d.code, year)] = _figure(d, year, values[(d.code, year)], resolved)
    return found


def _figure(
    d: DriverDef, year: int, ruled: Decimal | None, resolved: ResolvedDrivers
) -> Decimal | None:
    if d.history is None:  # a floor: the year's is the last quarter's
        return _number(resolved.get(d.code, year, "Q4").value)
    if isinstance(d.history, SeriesGrowth):
        annual = _number(resolved.get(d.code, year).value)
        agree = all(resolved.get(d.code, year, q).value == annual for q in QUARTERS)
        return annual if agree else None
    return ruled


def _number(value: object) -> Decimal | None:
    return value if isinstance(value, Decimal) else None
