"""Tornado and 2-D grid of a case's DCF value per share (FR-VAL-04; docs/erd/valuation.md
"Sensitivity" → Service). One load per request: a driver input re-runs the driver model on the
shifted drivers and the DCF on its forecast; a valuation input re-runs the DCF only, with every
other input (derived ones included) held at its base value."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.forecast.engines.driver import FORECAST_HORIZON, DriverModel
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import scenario_drivers
from bedrock.forecast.perturb import shift
from bedrock.models.company import Company
from bedrock.services.errors import InvalidSensitivity
from bedrock.services.valuation import CaseState, case_state
from bedrock.valuation.dcf import KEY as DCF_KEY
from bedrock.valuation.inputs import ResolvedInputs
from bedrock.valuation.interface import DcfDetails, ValuationForecast, valuation_forecast
from bedrock.valuation.registry import run_methods
from bedrock.valuation.sensitivity import (
    GRID_STEPS,
    Outcome,
    SensitivityGrid,
    SensitivityInput,
    TornadoBar,
    point,
    sensitivity_inputs,
    valuation_inputs_at,
)
from bedrock.valuation.sensitivity import (
    grid as build_grid,
)
from bedrock.valuation.sensitivity import (
    tornado as build_tornado,
)

__all__ = ["GridAxis", "GridResult", "TornadoResult", "grid", "tornado"]


@dataclass(frozen=True)
class TornadoResult:
    scenario_id: int
    case: str
    base_value: Decimal
    price: Decimal | None
    bars: list[TornadoBar]


@dataclass(frozen=True)
class GridAxis:
    item: SensitivityInput
    shifts: tuple[Decimal, ...]
    points: tuple[Decimal | None, ...]  # the input's value at each point


@dataclass(frozen=True)
class GridResult:
    scenario_id: int
    case: str
    base_value: Decimal
    price: Decimal | None
    x: GridAxis
    y: GridAxis
    grid: SensitivityGrid


@dataclass(frozen=True)
class _Base:
    state: CaseState
    value: Decimal
    rate: Decimal
    items: list[SensitivityInput]


def tornado(session: Session, company: Company, scenario_id: int, case: str) -> TornadoResult:
    """Each input moved down and up by its unit step, ranked by the range it gives the DCF
    value per share. Raises ScenarioNotFound, InvalidScenario, ForecastUnavailable (the forecast
    cannot run) and InvalidSensitivity (the base DCF has an error)."""
    base = _base(session, company, scenario_id, case)
    bars = build_tornado(base.value, base.items, lambda item, sign: _evaluate(base, [(item, sign)]))
    return TornadoResult(scenario_id, case, base.value, base.state.market.price, bars)


def grid(
    session: Session, company: Company, scenario_id: int, case: str, x: str, y: str
) -> GridResult:
    """5 × 5 DCF values per share over two inputs. Raises what `tornado` does, and
    InvalidSensitivity for an unknown or inapplicable code or the same code twice."""
    if x == y:
        raise InvalidSensitivity("Pick two different inputs")
    base = _base(session, company, scenario_id, case)
    by_code = {i.code: i for i in base.items}
    for code in (x, y):
        if code not in by_code:
            raise InvalidSensitivity(f"Unknown sensitivity input '{code}'")
    item_x, item_y = by_code[x], by_code[y]
    result = build_grid(
        item_x,
        item_y,
        base.value,
        base.state.market.price,
        lambda kx, ky: _evaluate(base, [(item_x, kx), (item_y, ky)]),
    )
    return GridResult(
        scenario_id,
        case,
        base.value,
        base.state.market.price,
        _axis(base, item_x, result.x_shifts),
        _axis(base, item_y, result.y_shifts),
        result,
    )


def _base(session: Session, company: Company, scenario_id: int, case: str) -> _Base:
    state = case_state(session, company, scenario_id, case)
    assert state.run is not None and state.forecast is not None
    outcome, details = _dcf(state.forecast, state, state.inputs)
    if isinstance(outcome, str) or details is None:
        raise InvalidSensitivity(outcome if isinstance(outcome, str) else "No DCF value")
    resolved = state.run.drivers.resolved
    labels = {d.code: d.label for d in scenario_drivers(state.history, state.run.drivers.settings)}
    return _Base(
        state, outcome, details.discount.rate, sensitivity_inputs(resolved, labels, state.inputs)
    )


def _dcf(
    forecast: ValuationForecast, state: CaseState, inputs: ResolvedInputs
) -> tuple[Outcome, DcfDetails | None]:
    """The DCF value per share (or its error text) with the DCF's details."""
    results = run_methods(forecast, state.market, inputs)
    dcf = next(r for r in results if r.key == DCF_KEY)
    if dcf.error is not None:
        return dcf.error, None
    assert isinstance(dcf.details, DcfDetails) and dcf.value_per_share is not None
    return dcf.value_per_share, dcf.details


def _evaluate(base: _Base, moves: list[tuple[SensitivityInput, int]]) -> Outcome:
    """The DCF value per share with each (input, k steps) applied; k = 0 changes nothing."""
    state = base.state
    assert state.run is not None and state.forecast is not None
    drivers = state.run.drivers.resolved
    inputs = state.inputs
    moved_drivers = False
    for item, k in moves:
        if k == 0:
            continue
        if item.kind == "driver":
            drivers = shift(drivers, item.code, item.step, item.mode, k)
            moved_drivers = True
        else:
            inputs = valuation_inputs_at(inputs, base.rate, item, k)
    forecast = state.forecast
    if moved_drivers:
        try:
            statements = DriverModel().run(
                state.history, drivers, FORECAST_HORIZON, state.run.drivers.settings
            )
        except ForecastUnavailable as unavailable:
            return unavailable.detail
        forecast = valuation_forecast(statements, drivers)
    return _dcf(forecast, state, inputs)[0]


def _axis(base: _Base, item: SensitivityInput, shifts: tuple[Decimal, ...]) -> GridAxis:
    start = _start_value(base, item)
    points = tuple(None if start is None else point(item, start, k) for k in GRID_STEPS)
    return GridAxis(item, shifts, points)


def _start_value(base: _Base, item: SensitivityInput) -> Decimal | None:
    """The input's base value: a driver's first forecast year (None when that year is not a
    number); the rate, growth or multiple itself."""
    state = base.state
    assert state.run is not None
    if item.kind == "driver":
        resolved = state.run.drivers.resolved
        value = resolved.get(item.code, resolved.years[0]).value
        return value if isinstance(value, Decimal) else None
    if item.code == "discount_rate":
        return base.rate
    own = state.inputs.get(item.code)
    return own if isinstance(own, Decimal) else None
