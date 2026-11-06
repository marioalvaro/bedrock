"""Valuation inputs of a scenario case and its valuations: DCF and multiple targets per case, the
scenario's three-case summary (FR-VAL-01..03, -05; docs/erd/valuation.md "Inputs", "Market data",
"Multiple targets", "API"). Valuations are computed on every read."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from bedrock.analysis.multiples import balance_sheet_shares
from bedrock.forecast.engines.driver import FORECAST_HORIZON
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import ForecastHistory, forecast_years
from bedrock.models.company import Company
from bedrock.models.scenario import CASES, Scenario, ScenarioCase
from bedrock.ratios.calculator import RatioTable
from bedrock.repositories import comps as comps_repo
from bedrock.repositories import prices as price_repo
from bedrock.repositories import scenarios as scenarios_repo
from bedrock.repositories import valuation_inputs as repo
from bedrock.services import comps as comps_service
from bedrock.services import ratios as ratios_service
from bedrock.services.errors import CompsSetNotFound, InvalidValuationInput
from bedrock.services.forecasts import CaseRun, run_case
from bedrock.services.scenarios import get_case, get_scenario, load_history
from bedrock.valuation.dcf import KEY as DCF_KEY
from bedrock.valuation.inputs import (
    INPUTS,
    TARGETS,
    DerivedValue,
    InputDef,
    InvalidInput,
    ResolvedInputs,
    derive,
    format_input,
    input_def,
    parse_input,
    resolve_inputs,
)
from bedrock.valuation.interface import (
    Bridge,
    MarketData,
    MultipleReference,
    ValuationForecast,
    ValuationResult,
    bridge_from_balance,
    valuation_forecast,
)
from bedrock.valuation.multiples import own_history_reference
from bedrock.valuation.registry import run_methods

__all__ = [
    "CaseState",
    "CaseValuation",
    "ForecastYear",
    "InputRow",
    "InputsView",
    "ScenarioSummary",
    "SummaryCase",
    "SummaryMethod",
    "case_state",
    "case_valuation",
    "put_valuation_inputs",
    "reset_valuation_inputs",
    "valuation_inputs",
    "valuation_summary",
]

DERIVED_CODES = ("cost_of_debt", "tax_rate", "debt_weight")
DCF_RATIO = "ev_fcf"  # the ratio whose caveat the DCF carries


@dataclass(frozen=True)
class ForecastYear:
    index: int  # 1..5
    fiscal_year: int
    label: str


@dataclass(frozen=True)
class InputRow:
    code: str
    label: str
    group: str
    unit: str | None
    kind: str
    choices: tuple[str, ...] | None
    value: str | None  # the resolved value as text
    source: str  # own | base | default | derived
    own: str | None  # the case's stored text
    note: str | None


@dataclass(frozen=True)
class InputsView:
    scenario_id: int
    case: str
    forecast_years: list[ForecastYear]
    rows: list[InputRow]
    warnings: list[str]  # why the derived values are missing, when the forecast cannot run


@dataclass(frozen=True)
class CaseValuation:
    scenario_id: int
    case: str
    results: list[ValuationResult]
    market: MarketData
    valuation_date: date | None
    caveats: dict[str, str]  # by result key
    warnings: list[str]


@dataclass(frozen=True)
class SummaryMethod:
    key: str
    label: str


@dataclass(frozen=True)
class SummaryCase:
    case: str
    value_per_share: dict[str, Decimal | None]
    upside: dict[str, Decimal | None]
    errors: dict[str, str]
    error: str | None  # the case's forecast cannot run


@dataclass(frozen=True)
class ScenarioSummary:
    scenario_id: int
    price: Decimal | None
    price_date: date | None
    methods: list[SummaryMethod]
    cases: list[SummaryCase]


@dataclass(frozen=True)
class CaseState:
    """Everything a case's valuation runs on, built from one load: the forecast and its
    resolution (None with `error` when it cannot run), the resolved inputs and the market data
    without references."""

    scenario: Scenario
    case: str
    history: ForecastHistory
    run: CaseRun | None
    forecast: ValuationForecast | None
    inputs: ResolvedInputs
    market: MarketData
    error: str | None


class _Context:
    """One scenario's loads, shared by its cases: the history, the close and the reference
    tables (loaded on first use)."""

    def __init__(self, session: Session, company: Company, scenario: Scenario) -> None:
        self.session, self.company, self.scenario = session, company, scenario
        self.history = load_history(session, company)
        self.close = price_repo.latest_close(session, company.id)
        self.shares = balance_sheet_shares(self.history.quarterly["BS"], self.history.annual["BS"])
        self.cases = scenarios_repo.cases_of(session, scenario.id)
        self._ratios: RatioTable | None = None
        self._comparisons: dict[int, Any] = {}

    def ratios(self) -> RatioTable:
        if self._ratios is None:
            self._ratios = ratios_service.ratios(self.session, self.company, "annual", "normalized")
        return self._ratios

    def comparison(self, set_id: int) -> comps_service.Comparison:
        if set_id not in self._comparisons:
            self._comparisons[set_id] = comps_service.comparison(
                self.session, self.company, set_id, "normalized"
            )
        found: comps_service.Comparison = self._comparisons[set_id]
        return found


# -- inputs ---------------------------------------------------------------------------------


def valuation_inputs(session: Session, company: Company, scenario_id: int, case: str) -> InputsView:
    """The case's inputs in catalog order with their resolved values and sources. When the forecast
    cannot run, the derived values are null and the detail is in `warnings`. Raises
    ScenarioNotFound and InvalidScenario."""
    scenario, kase = get_case(session, company, scenario_id, case)
    context = _Context(session, company, scenario)
    state = _state(context, case)
    return _view(scenario, kase, state, context)


def put_valuation_inputs(
    session: Session,
    company: Company,
    scenario_id: int,
    case: str,
    rows: Sequence[tuple[str, str | None]],
    now: datetime,
) -> InputsView:
    """Stores the case's own value per code (None deletes it, so it inherits again); codes not in
    `rows` are untouched. Every row is checked first; one transaction. Raises ScenarioNotFound,
    InvalidScenario and InvalidValuationInput."""
    scenario, kase = get_case(session, company, scenario_id, case)
    values = _checked(session, company, rows)
    stamp = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    repo.put_rows(session, kase.id, values, stamp)
    session.commit()
    return valuation_inputs(session, company, scenario_id, case)


def reset_valuation_inputs(
    session: Session, company: Company, scenario_id: int, case: str
) -> InputsView:
    """Deletes every stored input of the case (it inherits Base or the defaults again)."""
    _, kase = get_case(session, company, scenario_id, case)
    repo.delete_all(session, kase.id)
    session.commit()
    return valuation_inputs(session, company, scenario_id, case)


def _checked(
    session: Session, company: Company, rows: Sequence[tuple[str, str | None]]
) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for code, text in rows:
        try:
            input_def(code)
            if code in values:
                raise InvalidInput(f"{code} given twice")
            if text is None:
                values[code] = None
                continue
            parsed = parse_input(code, text)
        except InvalidInput as error:
            raise InvalidValuationInput(str(error)) from error
        if input_def(code).kind == "comps_set" and (
            comps_repo.get_set(session, company.id, int(parsed)) is None
        ):
            raise InvalidValuationInput(f"No such comps set: {parsed}")
        values[code] = format_input(parsed)
    return values


def _view(
    scenario: Scenario, kase: ScenarioCase, state: "CaseState", context: _Context
) -> InputsView:
    own = {r.code: r.value for r in repo.list_rows(context.session, [kase.id])}
    rows = []
    for definition, resolved in zip(INPUTS, state.inputs.rows, strict=True):
        rows.append(_row(definition, resolved.value, resolved.source, own, resolved.note))
    years = forecast_years(context.history, FORECAST_HORIZON.years)
    return InputsView(
        scenario_id=scenario.id,
        case=kase.case,
        forecast_years=[ForecastYear(i + 1, y, f"FY{y % 100:02d}E") for i, y in enumerate(years)],
        rows=rows,
        warnings=[] if state.error is None else [state.error],
    )


def _row(
    definition: InputDef,
    value: Any,
    source: str,
    own: dict[str, str],
    note: str | None,
) -> InputRow:
    return InputRow(
        code=definition.code,
        label=definition.label,
        group=definition.group,
        unit=definition.unit,
        kind=definition.kind,
        choices=definition.choices,
        value=None if value is None else format_input(value),
        source=source,
        own=own.get(definition.code),
        note=note,
    )


# -- valuation ------------------------------------------------------------------------------


def case_state(session: Session, company: Company, scenario_id: int, case: str) -> CaseState:
    """The case's valuation state (one load). Raises ScenarioNotFound, InvalidScenario and, when
    the forecast cannot run, ForecastUnavailable."""
    scenario, _ = get_case(session, company, scenario_id, case)
    state = _state(_Context(session, company, scenario), case)
    if state.error is not None:
        raise ForecastUnavailable(state.error)
    return state


def case_valuation(
    session: Session, company: Company, scenario_id: int, case: str
) -> CaseValuation:
    """The case's results (DCF, then the enabled multiple targets), market data and warnings.
    A method that cannot value has its error on its result. Raises ScenarioNotFound,
    InvalidScenario and ForecastUnavailable (the forecast cannot run)."""
    scenario, _ = get_case(session, company, scenario_id, case)
    context = _Context(session, company, scenario)
    state = _state(context, case)
    if state.error is not None:
        raise ForecastUnavailable(state.error)
    return _valued(context, state)


def valuation_summary(session: Session, company: Company, scenario_id: int) -> ScenarioSummary:
    """The scenario's three cases (base, bull, bear) valued from one history load; a case that
    cannot run has `error` and empty maps. Raises ScenarioNotFound."""
    scenario = get_scenario(session, company, scenario_id)
    context = _Context(session, company, scenario)
    methods: dict[str, str] = {}
    cases = []
    for case in CASES:
        state = _state(context, case)
        if state.error is not None:
            cases.append(SummaryCase(case, {}, {}, {}, state.error))
            continue
        valuation = _valued(context, state)
        for result in valuation.results:
            methods.setdefault(result.key, result.label)
        cases.append(
            SummaryCase(
                case=case,
                value_per_share={r.key: r.value_per_share for r in valuation.results},
                upside={r.key: r.upside for r in valuation.results},
                errors={r.key: r.error for r in valuation.results if r.error is not None},
                error=None,
            )
        )
    close = context.close
    return ScenarioSummary(
        scenario_id=scenario.id,
        price=None if close is None else close[1],
        price_date=None if close is None else close[0],
        methods=[SummaryMethod(k, v) for k, v in methods.items()],
        cases=cases,
    )


def _state(context: _Context, case: str) -> CaseState:
    session, scenario = context.session, context.scenario
    base_id = context.cases["base"].id
    stored = repo.list_rows(session, [context.cases[case].id, base_id])
    own = {r.code: r.value for r in stored if r.case_id == context.cases[case].id}
    base = {} if case == "base" else {r.code: r.value for r in stored if r.case_id == base_id}
    close = context.close
    run: CaseRun | None = None
    error: str | None = None
    try:
        run = run_case(session, scenario, case, context.history)
    except ForecastUnavailable as unavailable:
        error = unavailable.detail
    market = MarketData(
        price=None if close is None else close[1],
        price_date=None if close is None else close[0],
        shares=context.shares,
        bridge=(
            bridge_from_balance(run.statements.opening.balance)
            if run is not None
            else Bridge(*(Decimal(0),) * 5)
        ),
        references={},
    )
    derived: dict[str, DerivedValue]
    if run is None:
        derived = {code: DerivedValue(None, error) for code in DERIVED_CODES}
    else:
        resolved = run.drivers.resolved
        derived = derive(resolved, resolved.years[0], market)
    inputs = resolve_inputs(base, own, case == "base", derived)
    forecast = None if run is None else valuation_forecast(run.statements, run.drivers.resolved)
    return CaseState(scenario, case, context.history, run, forecast, inputs, market, error)


def _valued(context: _Context, state: CaseState) -> CaseValuation:
    assert state.run is not None and state.forecast is not None
    market = replace(state.market, references=_references(context, state.inputs))
    results = run_methods(state.forecast, market, state.inputs)
    caveats: dict[str, str] = {}
    for result in results:
        ratio = DCF_RATIO if result.key == DCF_KEY else result.key.removeprefix("multiple:")
        text = ratios_service.company_caveat(context.company, ratio)
        if text is not None:
            caveats[result.key] = text
    details = next((r.details for r in results if r.key == DCF_KEY), None)
    return CaseValuation(
        scenario_id=state.scenario.id,
        case=state.case,
        results=results,
        market=market,
        valuation_date=getattr(details, "valuation_date", None),
        caveats=caveats,
        warnings=state.run.warnings,
    )


def _references(context: _Context, inputs: ResolvedInputs) -> dict[str, MultipleReference]:
    references: dict[str, MultipleReference] = {}
    for code, (label, _) in TARGETS.items():
        source = inputs.get(f"{code}_source")
        if source == "own_history":
            references[code] = _own_history(context, inputs, code, label)
        elif source == "peer_median":
            references[code] = _peer_median(context, inputs, code, label)
    return references


def _own_history(
    context: _Context, inputs: ResolvedInputs, code: str, label: str
) -> MultipleReference:
    row = next((r for r in context.ratios().rows if r.code == code), None)
    percentile = inputs.get(f"{code}_percentile")
    assert isinstance(percentile, Decimal)
    return own_history_reference([] if row is None else row.values, percentile, label)


def _peer_median(
    context: _Context, inputs: ResolvedInputs, code: str, label: str
) -> MultipleReference:
    set_id = inputs.get("comps_set_id")
    if not isinstance(set_id, int):
        return MultipleReference(None, "peer_median", error="Choose a comps set")
    try:
        comparison = context.comparison(set_id)
    except CompsSetNotFound:
        return MultipleReference(None, "peer_median", error="The comps set no longer exists")
    row = next((r for r in comparison.table.rows if r.code == code), None)
    name = comparison.set.name
    if row is None or row.peer_median is None:
        return MultipleReference(
            None,
            "peer_median",
            comps_set=(set_id, name),
            error=f"{label}: no peer value in {name}",
        )
    return MultipleReference(row.peer_median, "peer_median", n=row.n, comps_set=(set_id, name))
