"""The valuation engines on the recorded companies (AAPL, MSFT, COST, DE) × Base, Bull, Bear at
the default inputs (docs/erd/valuation.md "Tests (M5)"): every DCF values, EV is the sum of its
present values, and the Gordon ↔ exit identities hold."""

from decimal import Decimal
from functools import cache

import pytest

from bedrock.analysis.multiples import balance_sheet_shares
from bedrock.forecast.engines.driver import FORECAST_HORIZON, DriverModel
from bedrock.valuation.inputs import ResolvedInputs, derive, resolve_inputs
from bedrock.valuation.interface import (
    DcfDetails,
    MarketData,
    MultipleReference,
    ValuationForecast,
    ValuationResult,
    bridge_from_balance,
    valuation_forecast,
)
from bedrock.valuation.registry import run_methods
from tests.test_driver_model_fixtures import GROWTH, SCENARIOS, TICKERS, case_drivers, history

D = Decimal
PRICES = {"AAPL": D(230), "MSFT": D(420), "COST": D(900), "DE": D(400)}
REFERENCES = {
    "pe": MultipleReference(D(25), "own_history", percentile=D("0.5"), n=5),
    "ev_ebitda": MultipleReference(D(18), "own_history", percentile=D("0.5"), n=5),
}


@cache
def _case(ticker: str, scenario: str) -> tuple[ValuationForecast, MarketData, ResolvedInputs]:
    h = history(ticker)
    drivers = case_drivers(ticker, scenario, FORECAST_HORIZON)
    statements = DriverModel().run(h, drivers, FORECAST_HORIZON, GROWTH)
    market = MarketData(
        price=PRICES[ticker],
        price_date=statements.opening.period.end,
        shares=balance_sheet_shares(h.quarterly["BS"], h.annual["BS"]),
        bridge=bridge_from_balance(statements.opening.balance),
        references=REFERENCES,
    )
    derived = derive(drivers, drivers.years[0], market)
    inputs = resolve_inputs({}, {}, is_base=True, derived=derived)
    return valuation_forecast(statements, drivers), market, inputs


def _dcf(results: list[ValuationResult]) -> tuple[ValuationResult, DcfDetails]:
    result = results[0]
    assert result.key == "dcf_fcff"
    assert result.error is None, result.error
    assert isinstance(result.details, DcfDetails)
    return result, result.details


def _relative(a: Decimal | None, b: Decimal | None) -> Decimal:
    assert a is not None and b is not None
    return abs(a - b) / abs(b)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("ticker", TICKERS)
def test_every_case_values_at_the_default_inputs(ticker: str, scenario: str) -> None:
    forecast, market, inputs = _case(ticker, scenario)
    assert inputs.source("debt_weight") == "derived" and inputs.get("debt_weight") is not None
    assert inputs.get("tax_rate") is not None
    results = run_methods(forecast, market, inputs)
    assert [r.key for r in results] == ["dcf_fcff", "multiple:pe", "multiple:ev_ebitda"]
    result, details = _dcf(results)
    assert result.value_per_share is not None and result.value_per_share.is_finite()
    assert result.upside is not None
    assert len(details.periods) == 5
    assert details.periods[0].stub == (
        forecast.statements.opening.period.fiscal_period in ("Q1", "Q2", "Q3")
    )
    assert result.enterprise_value == details.sum_present_value + details.terminal.present_value
    assert details.sum_present_value == sum((p.present_value for p in details.periods), D(0))
    for target in results[1:]:
        if target.error is None:
            assert target.value_per_share is not None and target.value_per_share.is_finite()
        else:
            assert target.error.endswith("is not positive"), target.error


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("ticker", TICKERS)
def test_gordon_and_exit_identities_hold(ticker: str, scenario: str) -> None:
    forecast, market, inputs = _case(ticker, scenario)
    gordon, details = _dcf(run_methods(forecast, market, inputs))
    multiple = details.terminal.implied_exit_multiple
    assert multiple is not None
    exit_inputs = inputs.with_values(
        {"terminal_method": "exit_multiple", "exit_multiple": multiple}
    )
    exit_run, exit_details = _dcf(run_methods(forecast, market, exit_inputs))
    assert _relative(exit_run.enterprise_value, gordon.enterprise_value) <= D("1e-12")
    growth = exit_details.terminal.implied_growth
    assert growth is not None
    back, _ = _dcf(run_methods(forecast, market, inputs.with_values({"terminal_growth": growth})))
    assert _relative(back.enterprise_value, gordon.enterprise_value) <= D("1e-12")


@pytest.mark.parametrize("ticker", TICKERS)
def test_bull_is_worth_more_than_base_and_base_more_than_bear(ticker: str) -> None:
    values = [
        _dcf(run_methods(*_case(ticker, scenario)))[0].value_per_share
        for scenario in ("bull", "base", "bear")
    ]
    assert values[0] is not None and values[1] is not None and values[2] is not None
    assert values[0] > values[1] > values[2]
