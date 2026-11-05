"""The annual figure of a forecast year built from its quarters (docs/erd/forecasting.md "Year
modes" → Roll-up). Pure."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from bedrock.forecast.drivers import QUARTERS, DriverDef, SeriesGrowth, segment_code, segment_id
from bedrock.forecast.engines.driver import ForecastStatements, segment_quarter
from bedrock.forecast.errors import ForecastUnavailable
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
    a segment's growth is its four quarters summed over the previous year's four (actual or
    forecast: the engine's own chain, `segment_quarter`); where a quarter it needs has no value,
    like a KPI growth (volume, price: the forecast carries no quarterly series), it is the year's
    driver while the year's four quarters agree with it and None once one differs; `min_cash`, a
    floor, is the last quarter's. A year the statements do not cover is left out."""
    annual = statements.annual()
    span = {(p.fiscal_year, p.fiscal_period) for p in statements.periods if p.fiscal_period != "FY"}
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
            found[(d.code, year)] = _figure(
                d, year, values[(d.code, year)], resolved, history, span
            )
    return found


def _figure(
    d: DriverDef,
    year: int,
    ruled: Decimal | None,
    resolved: ResolvedDrivers,
    history: ForecastHistory,
    span: set[tuple[int, str]],
) -> Decimal | None:
    if d.history is None:  # a floor: the year's is the last quarter's
        return _number(resolved.get(d.code, year, "Q4").value)
    if isinstance(d.history, SeriesGrowth):
        implied = _segment_growth(d.code, year, resolved, history, span)
        if implied is not None:
            return implied
        annual = _number(resolved.get(d.code, year).value)
        agree = all(resolved.get(d.code, year, q).value == annual for q in QUARTERS)
        return annual if agree else None
    return ruled


def _segment_growth(
    code: str,
    year: int,
    resolved: ResolvedDrivers,
    history: ForecastHistory,
    span: set[tuple[int, str]],
) -> Decimal | None:
    """A segment's growth implied by its quarters: sum of the year's four over the previous
    year's four; None for a driver that is not a segment's, or when a quarter has no value."""
    id_ = segment_id(code)
    series = next((s for s in history.segment_series if s.id == id_), None)
    if series is None:
        return None

    def growth(y: int, q: str) -> Decimal:
        value = resolved.get(segment_code(series.id), y, q).value
        if not isinstance(value, Decimal):
            raise ForecastUnavailable(f"No growth for {code} in {q} FY{y}")
        return value

    try:
        now = sum((segment_quarter(series, year, q, span, growth) for q in QUARTERS), Decimal(0))
        before = sum(
            (segment_quarter(series, year - 1, q, span, growth) for q in QUARTERS), Decimal(0)
        )
    except ForecastUnavailable:
        return None
    return now / before - 1 if before else None


def _number(value: object) -> Decimal | None:
    return value if isinstance(value, Decimal) else None
