"""A scenario's forecast as a statement table, and the scenario comparison (FR-FCST-01, -02, -04,
-06; docs/erd/forecasting.md "API")."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from bedrock.forecast.engines.driver import FORECAST_HORIZON, DriverModel, ForecastStatements
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import ForecastHistory
from bedrock.forecast.integrity import IntegrityCheck
from bedrock.models.company import Company
from bedrock.models.scenario import Scenario
from bedrock.services.errors import UnknownLineItem
from bedrock.services.scenarios import get_scenario, list_scenarios, load_history, resolve_scenario
from bedrock.services.statements import canonical_items
from bedrock.statements.build import StatementTable, extend_table
from bedrock.statements.periods import Period
from bedrock.statements.view import select_periods, trim_periods

__all__ = [
    "Comparison",
    "ComparedScenario",
    "Forecast",
    "ForecastFreq",
    "LineItem",
    "compare",
    "forecast_table",
]

ForecastFreq = Literal["annual", "quarterly"]
SHOWN_ACTUALS: dict[ForecastFreq, int] = {"annual": 3, "quarterly": 4}
COMPARE_CODES = (
    "revenue",
    "operating_income",
    "net_income",
    "eps_diluted",
    "free_cash_flow",
    "cash",
    "total_debt",
)


@dataclass(frozen=True)
class Forecast:
    """The actual periods shown then the forecast ones (provenance `forecast`), with the
    integrity checks and warnings of the forecast periods shown."""

    table: StatementTable
    forecast_keys: frozenset[str]
    integrity: list[IntegrityCheck]
    warnings: list[str]


@dataclass(frozen=True)
class LineItem:
    code: str
    label: str
    unit: str


@dataclass(frozen=True)
class ComparedScenario:
    id: int
    name: str
    values: dict[str, list[Decimal | None]]  # aligned with the comparison's periods
    error: str | None  # the forecast's 422 detail; then `values` is empty


@dataclass(frozen=True)
class Comparison:
    periods: list[Period]  # forecast periods only: the union of the scenarios' horizons
    codes: list[LineItem]
    scenarios: list[ComparedScenario]


def forecast_table(
    session: Session, company: Company, scenario_id: int, statement: str, freq: ForecastFreq
) -> Forecast:
    """The last SHOWN_ACTUALS actual periods of the normalized statement, then the scenario's
    forecast periods of `freq`. YoY, common size and the balance check run over the combined
    columns. Raises ScenarioNotFound and ForecastUnavailable."""
    scenario = get_scenario(session, company, scenario_id)
    history = load_history(session, company)
    statements, warnings = _run(session, scenario, history)
    periods = statements.annual() if freq == "annual" else statements.quarterly()
    first = (periods[0].fiscal_year, periods[0].fiscal_period)
    tables = history.annual if freq == "annual" else history.quarterly
    actual = trim_periods(tables[statement])
    before = [p.key for p in actual.periods if (p.fiscal_year, p.fiscal_period) < first]
    combined = extend_table(select_periods(actual, before), periods, statements.values)
    keys = frozenset(p.key for p in periods)
    return Forecast(
        table=select_periods(combined, set(before[-SHOWN_ACTUALS[freq] :]) | keys),
        forecast_keys=keys,
        integrity=[c for c in statements.integrity if c.period_key in keys],
        warnings=warnings,
    )


def compare(
    session: Session,
    company: Company,
    freq: ForecastFreq,
    codes: Sequence[str] | None,
    now: datetime,
) -> Comparison:
    """Every scenario of the company (creating the defaults on the first call) on `codes`
    (default COMPARE_CODES) over the union of their forecast periods of `freq`; a scenario that
    cannot run has its detail as `error`. Raises UnknownLineItem."""
    items = _line_items(codes or COMPARE_CODES)
    scenarios = list_scenarios(session, company, now)
    history = load_history(session, company)
    runs: list[tuple[Scenario, ForecastStatements | None, str | None]] = []
    periods: dict[str, Period] = {}
    for scenario in scenarios:
        try:
            statements, _ = _run(session, scenario, history)
            shown = statements.annual() if freq == "annual" else statements.quarterly()
        except ForecastUnavailable as error:
            runs.append((scenario, None, error.detail))
            continue
        periods.update((p.key, p) for p in shown)
        runs.append((scenario, statements, None))
    ordered = sorted(periods.values(), key=lambda p: p.end)
    compared = []
    for scenario, run, failure in runs:
        values: dict[str, list[Decimal | None]] = {}
        if run is not None:
            keys = {p.key for p in run.periods}
            values = {
                item.code: [run.get(item.code, p.key) if p.key in keys else None for p in ordered]
                for item in items
            }
        compared.append(ComparedScenario(scenario.id, scenario.name, values, failure))
    return Comparison(ordered, items, compared)


def _run(
    session: Session, scenario: Scenario, history: ForecastHistory
) -> tuple[ForecastStatements, list[str]]:
    drivers = resolve_scenario(session, scenario, history)
    statements = DriverModel().run(
        history,
        drivers.resolved,
        FORECAST_HORIZON,
        drivers.settings,
    )
    return statements, [*drivers.resolved.warnings, *statements.warnings]


def _line_items(codes: Sequence[str]) -> list[LineItem]:
    by_code = {
        i.code: i for i in canonical_items() if i.statement in ("IS", "BS", "CF") and not i.custom
    }
    unknown = [c for c in codes if c not in by_code]
    if unknown:
        raise UnknownLineItem(f"Unknown line item {', '.join(repr(c) for c in unknown)}")
    return [LineItem(c, by_code[c].label, by_code[c].unit) for c in dict.fromkeys(codes)]
