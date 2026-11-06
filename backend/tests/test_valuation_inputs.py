"""The valuation input catalog, parsing, resolution and derived defaults (docs/erd/valuation.md
"Inputs (M5)"). Pure."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.forecast.history import FLAT
from bedrock.forecast.resolve import Resolved, ResolvedDrivers
from bedrock.valuation.inputs import (
    INPUTS,
    DerivedValue,
    InvalidInput,
    derive,
    format_input,
    parse_input,
    resolve_inputs,
)
from bedrock.valuation.interface import Bridge
from tests.valuation_data import drivers, market

D = Decimal
TARGETS = ("pe", "ev_ebitda", "p_fcf", "ev_sales")
NO_CLOSE = "No close: set the debt weight or a direct discount rate"


def test_the_catalog_is_in_the_erd_order() -> None:
    assert [d.code for d in INPUTS] == [
        "discount_method",
        "discount_rate",
        "risk_free_rate",
        "equity_risk_premium",
        "beta",
        "cost_of_debt",
        "tax_rate",
        "debt_weight",
        "terminal_method",
        "terminal_growth",
        "exit_multiple",
        "mid_year",
        *[f"{m}_source" for m in TARGETS],
        *[f"{m}_multiple" for m in TARGETS],
        *[f"{m}_percentile" for m in TARGETS],
        *[f"{m}_year" for m in TARGETS],
        "comps_set_id",
    ]
    assert {d.group for d in INPUTS} == {"Discount rate", "Terminal value", "Multiples"}


def test_an_input_nobody_sets_takes_its_default() -> None:
    inputs = resolve_inputs({}, {}, is_base=True, derived={})
    expected: dict[str, object] = {
        "discount_method": "wacc",
        "discount_rate": D("0.09"),
        "risk_free_rate": D("0.04"),
        "equity_risk_premium": D("0.05"),
        "beta": D(1),
        "terminal_method": "gordon",
        "terminal_growth": D("0.025"),
        "exit_multiple": D(12),
        "mid_year": True,
        "pe_source": "own_history",
        "ev_ebitda_source": "own_history",
        "p_fcf_source": "off",
        "ev_sales_source": "off",
        "pe_multiple": None,
        "ev_sales_multiple": None,
        "pe_percentile": D("0.5"),
        "ev_sales_percentile": D("0.5"),
        "pe_year": 1,
        "ev_sales_year": 1,
        "comps_set_id": None,
    }
    for code, value in expected.items():
        assert inputs.get(code) == value, code
        assert inputs.source(code) == "default", code
    for code in ("cost_of_debt", "tax_rate", "debt_weight"):
        assert inputs.get(code) is None
        assert inputs.source(code) == "derived"
    assert [r.code for r in inputs.rows] == [d.code for d in INPUTS]


# -- parsing ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "text", "value"),
    [
        ("beta", "1.2", D("1.2")),
        ("beta", " 0 ", D(0)),
        ("beta", "5", D(5)),
        ("terminal_growth", "-0.05", D("-0.05")),
        ("exit_multiple", "100", D(100)),
        ("pe_year", "5", 1 * 5),
        ("pe_year", "1", 1),
        ("discount_method", "direct", "direct"),
        ("pe_source", "peer_median", "peer_median"),
        ("mid_year", "false", False),
        ("mid_year", "true", True),
        ("comps_set_id", "7", 7),
    ],
)
def test_each_kind_parses_its_text(code: str, text: str, value: object) -> None:
    parsed = parse_input(code, text)
    assert parsed == value
    assert type(parsed) is type(value)


@pytest.mark.parametrize(
    ("code", "text", "message"),
    [
        ("beta", "1e5", "beta must be a number"),
        ("beta", "inf", "beta must be a number"),
        ("beta", "NaN", "beta must be a number"),
        ("beta", "abc", "beta must be a number"),
        ("beta", "", "beta must be a number"),
        ("beta", "5.01", "beta must be in [0, 5]"),
        ("beta", "-0.1", "beta must be in [0, 5]"),
        ("discount_rate", "0.005", "discount_rate must be in [0.01, 0.5]"),
        ("exit_multiple", "0", "exit_multiple must be in (0, 100]"),
        ("terminal_growth", "0.11", "terminal_growth must be in [-0.05, 0.1]"),
        ("pe_multiple", "1000.5", "pe_multiple must be in (0, 1000]"),
        ("debt_weight", "0.995", "debt_weight must be in [0, 0.99]"),
        ("discount_method", "capm", "discount_method must be one of wacc, direct"),
        ("pe_source", "Manual", "pe_source must be one of off, manual, own_history, peer_median"),
        ("mid_year", "maybe", "mid_year must be true or false"),
        ("mid_year", "True", "mid_year must be true or false"),
        ("pe_year", "0", "pe_year must be in [1, 5]"),
        ("pe_year", "6", "pe_year must be in [1, 5]"),
        ("pe_year", "1.5", "pe_year must be a whole number"),
        ("pe_year", "²", "pe_year must be a whole number"),
        ("comps_set_id", "0", "comps_set_id must be a comps set id"),
        ("comps_set_id", "-3", "comps_set_id must be a comps set id"),
        ("comps_set_id", "x", "comps_set_id must be a comps set id"),
        ("wacc", "0.1", "Unknown valuation input 'wacc'"),
    ],
)
def test_parsing_refuses_with_a_message(code: str, text: str, message: str) -> None:
    with pytest.raises(InvalidInput) as raised:
        parse_input(code, text)
    assert str(raised.value) == message


def test_the_stored_text_is_the_plain_string_of_the_parsed_value() -> None:
    assert format_input(parse_input("pe_multiple", "1,00.50")) == "100.50"
    assert format_input(D("1E+1")) == "10"
    assert format_input(True) == "true"
    assert format_input(False) == "false"
    assert format_input(3) == "3"
    assert format_input("direct") == "direct"


# -- resolution ------------------------------------------------------------------------------


def test_base_takes_its_own_row_else_the_default() -> None:
    inputs = resolve_inputs({"beta": "1.3"}, {"beta": "1.3"}, is_base=True, derived={})
    assert (inputs.get("beta"), inputs.source("beta")) == (D("1.3"), "own")
    assert (inputs.get("risk_free_rate"), inputs.source("risk_free_rate")) == (D("0.04"), "default")


def test_bull_takes_its_own_row_then_bases_then_the_default() -> None:
    base = {"beta": "1.3", "risk_free_rate": "0.03"}
    inputs = resolve_inputs(base, {"beta": "0.9"}, is_base=False, derived={})
    assert (inputs.get("beta"), inputs.source("beta")) == (D("0.9"), "own")
    assert (inputs.get("risk_free_rate"), inputs.source("risk_free_rate")) == (D("0.03"), "base")
    assert (inputs.get("equity_risk_premium"), inputs.source("equity_risk_premium")) == (
        D("0.05"),
        "default",
    )


def test_a_set_value_overrides_a_derived_default() -> None:
    derived = {"tax_rate": DerivedValue(D("0.2"), "From the forecast's FY2026 tax rate")}
    inputs = resolve_inputs({"tax_rate": "0.15"}, {}, is_base=False, derived=derived)
    assert (inputs.get("tax_rate"), inputs.source("tax_rate")) == (D("0.15"), "base")
    assert inputs.note("tax_rate") is None


def test_a_derived_default_carries_its_note() -> None:
    derived = {"tax_rate": DerivedValue(D("0.2"), "From the forecast's FY2026 tax rate")}
    inputs = resolve_inputs({}, {}, is_base=False, derived=derived)
    assert (inputs.get("tax_rate"), inputs.source("tax_rate")) == (D("0.2"), "derived")
    assert inputs.note("tax_rate") == "From the forecast's FY2026 tax rate"


def test_a_derived_default_that_follows_another_input_takes_its_resolved_value() -> None:
    derived = {
        "cost_of_debt": DerivedValue(
            None, "Risk-free rate: the forecast has no interest rate", follows="risk_free_rate"
        )
    }
    inputs = resolve_inputs({"risk_free_rate": "0.035"}, {}, is_base=False, derived=derived)
    assert (inputs.get("cost_of_debt"), inputs.source("cost_of_debt")) == (D("0.035"), "derived")
    assert inputs.note("cost_of_debt") == "Risk-free rate: the forecast has no interest rate"


def test_with_values_replaces_values_and_leaves_the_original() -> None:
    inputs = resolve_inputs({}, {}, is_base=True, derived={})
    moved = inputs.with_values({"terminal_growth": D("0.03")})
    assert moved.get("terminal_growth") == D("0.03")
    assert inputs.get("terminal_growth") == D("0.025")
    assert moved.get("beta") == D(1)


def test_an_unknown_code_raises_key_error() -> None:
    inputs = resolve_inputs({}, {}, is_base=True, derived={})
    with pytest.raises(KeyError):
        inputs.get("wacc")


def test_a_stored_row_that_does_not_parse_raises() -> None:
    with pytest.raises(InvalidInput):
        resolve_inputs({}, {"beta": "9"}, is_base=True, derived={})


# -- derived defaults ------------------------------------------------------------------------


def _rates(interest: Decimal | int | str, tax: Decimal | int | str = "0.21") -> ResolvedDrivers:
    return drivers({"interest_rate": interest, "tax_rate": tax})


def test_cost_of_debt_is_the_first_year_interest_rate_when_positive() -> None:
    out = derive(_rates("0.045"), 2026, market())
    assert out["cost_of_debt"] == DerivedValue(
        D("0.045"), "From the forecast's FY2026 interest rate"
    )


def test_a_zero_interest_rate_makes_cost_of_debt_the_risk_free_rate() -> None:
    out = derive(_rates(0), 2026, market())
    assert out["cost_of_debt"] == DerivedValue(
        None, "Risk-free rate: the forecast has no interest rate", follows="risk_free_rate"
    )
    inputs = resolve_inputs({}, {}, is_base=True, derived=out)
    assert inputs.get("cost_of_debt") == D("0.04")


def test_only_the_first_year_counts() -> None:
    values = dict(_rates("0.05").values)
    values[("interest_rate", 2026)] = Resolved(D(0), "own")
    rates = ResolvedDrivers(("interest_rate", "tax_rate"), (2026, 2027), values, (), frozenset())
    assert derive(rates, 2026, market())["cost_of_debt"].value is None
    assert derive(rates, 2027, market())["cost_of_debt"].value == D("0.05")


def test_the_tax_rate_is_the_first_year_tax_rate() -> None:
    out = derive(_rates("0.05", "0.18"), 2026, market())
    assert out["tax_rate"] == DerivedValue(D("0.18"), "From the forecast's FY2026 tax rate")


def test_a_flat_or_missing_driver_derives_nothing() -> None:
    values = {
        ("interest_rate", 2026): Resolved(FLAT, "default"),
        ("tax_rate", 2026): Resolved(None, None),
    }
    rates = ResolvedDrivers(("interest_rate", "tax_rate"), (2026,), values, (), frozenset())
    out = derive(rates, 2026, market())
    assert out["cost_of_debt"].value is None and out["cost_of_debt"].follows == "risk_free_rate"
    assert out["tax_rate"] == DerivedValue(None, "The forecast has no FY2026 tax rate")


def test_the_debt_weight_is_debt_over_debt_plus_market_value() -> None:
    zero = D(0)
    bridge = Bridge(D(250), D(999), zero, zero, zero)  # cash does not count
    m = market(price=50, shares=15, price_date=date(2026, 11, 4), bridge=bridge)
    out = derive(_rates("0.05"), 2026, m)
    # D = 250, E = 50 × 15 = 750
    assert out["debt_weight"] == DerivedValue(
        D("0.25"), "Market weights at the close of 2026-11-04"
    )


@pytest.mark.parametrize(
    ("price", "shares", "note"),
    [
        (None, 10, NO_CLOSE),
        (50, None, "No share count: set the debt weight or a direct discount rate"),
        (50, 0, "No share count: set the debt weight or a direct discount rate"),
    ],
)
def test_no_debt_weight_without_a_close_or_shares(
    price: int | None, shares: int | None, note: str
) -> None:
    out = derive(_rates("0.05"), 2026, market(price=price, shares=shares))
    assert out["debt_weight"] == DerivedValue(None, note)


def test_no_debt_weight_when_debt_plus_equity_is_not_positive() -> None:
    zero = D(0)
    m = market(price=0, shares=10, bridge=Bridge(zero, zero, zero, zero, zero))
    out = derive(_rates("0.05"), 2026, m)
    assert out["debt_weight"] == DerivedValue(
        None, "No market weights: debt plus market value is not positive"
    )


def test_derive_without_a_resolution_derives_only_the_debt_weight() -> None:
    out = derive(None, 2026, market(price=None))
    assert out["debt_weight"] == DerivedValue(None, NO_CLOSE)
    assert out["tax_rate"].value is None
    assert out["cost_of_debt"].follows == "risk_free_rate"
