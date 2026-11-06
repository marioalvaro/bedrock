"""DCF on FCFF (docs/erd/valuation.md "DCF on FCFF (M5)", "Interface"): hand-computed synthetic
forecasts, the identities and every error. Pure."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.forecast.history import FLAT
from bedrock.forecast.resolve import Resolved, ResolvedDrivers
from bedrock.valuation.dcf import DcfFcff
from bedrock.valuation.inputs import ResolvedInputs, resolve_inputs
from bedrock.valuation.interface import (
    Bridge,
    DcfDetails,
    DiscountDetails,
    MarketData,
    ValuationForecast,
    ValuationResult,
    bridge_from_balance,
    upside,
    valuation_forecast,
)
from tests.valuation_data import (
    FYE,
    YEARS,
    annual_forecast,
    flows,
    forecast,
    market,
    quarter_forecast,
)

D = Decimal


def test_net_claims_add_debt_minority_and_temporary_equity_less_cash_and_investments() -> None:
    bridge = Bridge(
        total_debt=D(100),
        cash=D(30),
        short_term_investments=D(20),
        minority_interest=D(5),
        temporary_equity=D(2),
    )
    assert bridge.net_claims == D(57)


def test_the_bridge_reads_the_opening_balance_and_ignores_negative_nci() -> None:
    bridge = bridge_from_balance(
        {
            "short_term_debt": D(10),
            "long_term_debt": D(90),
            "cash": D(30),
            "short_term_investments": D(20),
            "nci": D(-4),
            "temporary_equity": D(3),
            "operating_lease_liabilities_noncurrent": D(1000),
        }
    )
    assert bridge == Bridge(D(100), D(30), D(20), D(0), D(3))


def test_a_missing_balance_line_counts_zero() -> None:
    assert bridge_from_balance({"nci": D(7)}) == Bridge(D(0), D(0), D(0), D(7), D(0))


def test_upside_is_value_over_price_less_one_and_null_without_a_positive_price() -> None:
    assert upside(D(120), D(100)) == D("0.2")
    assert upside(None, D(100)) is None
    assert upside(D(120), None) is None
    assert upside(D(120), D(0)) is None


def test_the_valuation_forecast_carries_years_and_every_period_tax_rate() -> None:
    statements = quarter_forecast()
    years = YEARS
    values = {("tax_rate", y): Resolved(D("0.25"), "own") for y in years}
    values[("tax_rate", 2026)] = Resolved(D("0.2"), "own")
    values.update({("receivable_days", y): Resolved(FLAT, "default") for y in years})
    quarters = {("tax_rate", 2026, "Q3"): Resolved(D("0.1"), "own")}
    drivers = ResolvedDrivers(
        ("tax_rate", "receivable_days"), years, values, (), frozenset(), quarters
    )
    forecast = valuation_forecast(statements, drivers)
    assert forecast.statements is statements
    assert forecast.years == years
    assert forecast.tax_rates["FY2026"] == D("0.2")
    assert forecast.tax_rates["FY2026Q3"] == D("0.1")
    assert forecast.tax_rates["FY2026Q4"] == D("0.2")  # from its year
    assert forecast.tax_rates["FY2027"] == D("0.25")
    assert set(forecast.tax_rates) == {p.key for p in statements.periods}


def test_the_annual_helper_builds_five_years() -> None:
    assert [p.key for p in annual_forecast().annual()] == [f"FY{y}" for y in range(2026, 2031)]


# -- DCF on FCFF -----------------------------------------------------------------------------

YEAR = D("365.25")
TOLERANCE = D("1e-20")
NO_CLOSE = "No close: set the debt weight or a direct discount rate"


def _inputs(**texts: str) -> ResolvedInputs:
    return resolve_inputs({}, texts, is_base=True, derived={})


def _direct(**texts: str) -> ResolvedInputs:
    base = {"discount_method": "direct", "discount_rate": "0.1", "mid_year": "false"}
    return _inputs(**{**base, **texts})


def _five_years(sbc: int = 0) -> ValuationForecast:
    """FCFF = 0.75 × OI + 10 − 15 + (−2 − 1 + 3) = 70, 77.5, 85, 92.5, 100; EBITDA_5 = 150."""
    lines = {
        2026 + i: flows(oi, 10, -15, -2, -1, 3, sbc=sbc)
        for i, oi in enumerate((100, 110, 120, 130, 140))
    }
    return forecast(annual_forecast(lines), tax="0.25")


def _bridge() -> Bridge:
    return Bridge(D(200), D(50), D(0), D(0), D(0))  # net claims 150


def _dcf(
    inputs: ResolvedInputs,
    f: ValuationForecast | None = None,
    m: MarketData | None = None,
) -> ValuationResult:
    results = DcfFcff().value(f or _five_years(), m or market(bridge=_bridge()), inputs)
    assert len(results) == 1
    return results[0]


def _details(result: ValuationResult) -> DcfDetails:
    assert isinstance(result.details, DcfDetails)
    return result.details


def _close(a: Decimal | None, b: Decimal, tolerance: Decimal = TOLERANCE) -> bool:
    return a is not None and abs(a - b) <= tolerance * max(abs(b), D(1))


FCFF = [D(70), D("77.5"), D(85), D("92.5"), D(100)]
END_DAYS = [365, 730, 1096, 1461, 1826]  # FY2026..FY2030 ends from 2025-12-31


def test_an_annual_forecast_at_a_direct_rate_without_mid_year() -> None:
    result = _dcf(_direct())
    details = _details(result)
    assert (result.key, result.method, result.label) == ("dcf_fcff", "dcf_fcff", "DCF (FCFF)")
    assert result.error is None
    assert details.discount == DiscountDetails("direct", D("0.1"))
    assert details.valuation_date == FYE
    assert [p.fcff for p in details.periods] == FCFF
    assert [p.stub for p in details.periods] == [False] * 5
    first = details.periods[0]
    assert (first.period_key, first.label, first.start, first.end) == (
        "FY2026",
        "FY26E",
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    assert (first.nopat, first.d_and_a, first.change_working_capital, first.capex) == (
        D(75),
        D(10),
        D(0),
        D(-15),
    )
    pvs = []
    for p, cash, days in zip(details.periods, FCFF, END_DAYS, strict=True):
        tau = D(days) / YEAR
        assert p.years == tau
        assert _close(p.discount_factor, D("1.1") ** -tau)
        assert _close(p.present_value, cash * D("1.1") ** -tau)
        pvs.append(cash * D("1.1") ** -tau)
    terminal = details.terminal
    # Gordon: 100 × 1.025 ÷ (0.1 − 0.025)
    tv = D(100) * D("1.025") / D("0.075")
    assert terminal.method == "gordon"
    assert (terminal.growth, terminal.exit_multiple) == (D("0.025"), None)
    assert (terminal.base_fcff, terminal.base_ebitda) == (D(100), D(150))
    assert _close(terminal.value, tv)
    assert terminal.years == D(1826) / YEAR
    pv_tv = tv * D("1.1") ** -(D(1826) / YEAR)
    assert _close(terminal.present_value, pv_tv)
    ev = sum(pvs, D(0)) + pv_tv
    assert _close(result.enterprise_value, ev)
    assert _close(result.equity_value, ev - 150)
    assert _close(result.value_per_share, (ev - 150) / 10)
    assert _close(result.upside, (ev - 150) / 10 / 50 - 1)
    assert _close(details.sum_present_value, sum(pvs, D(0)))
    assert _close(details.terminal_share, pv_tv / ev)
    assert _close(terminal.implied_exit_multiple, tv / 150)


def test_ev_is_the_sum_of_present_values_exactly() -> None:
    for inputs in (_direct(), _direct(mid_year="true"), _direct(terminal_method="exit_multiple")):
        result = _dcf(inputs)
        details = _details(result)
        assert details.sum_present_value == sum((p.present_value for p in details.periods), D(0))
        assert result.enterprise_value == details.sum_present_value + details.terminal.present_value


def test_mid_year_discounts_each_window_at_its_midpoint() -> None:
    details = _details(_dcf(_direct(mid_year="true")))
    starts = [0, *END_DAYS[:-1]]
    for p, start, end in zip(details.periods, starts, END_DAYS, strict=True):
        assert p.years == (D(start) / YEAR + D(end) / YEAR) / 2
    # the terminal value is not shifted
    assert details.terminal.years == D(1826) / YEAR
    assert details.mid_year is True


def test_a_wacc_rate_from_capm_and_after_tax_debt() -> None:
    inputs = _inputs(
        risk_free_rate="0.04",
        beta="1.2",
        equity_risk_premium="0.05",
        cost_of_debt="0.06",
        tax_rate="0.25",
        debt_weight="0.2",
    )
    discount = _details(_dcf(inputs)).discount
    # k_e = 0.04 + 1.2 × 0.05 = 0.10; k_d(1 − t) = 0.045; r = 0.8 × 0.10 + 0.2 × 0.045
    assert discount == DiscountDetails(
        method="wacc",
        rate=D("0.089"),
        cost_of_equity=D("0.10"),
        after_tax_cost_of_debt=D("0.045"),
        risk_free_rate=D("0.04"),
        equity_risk_premium=D("0.05"),
        beta=D("1.2"),
        cost_of_debt=D("0.06"),
        tax_rate=D("0.25"),
        debt_weight=D("0.2"),
        equity_weight=D("0.8"),
    )


def test_a_stub_year_is_its_forecast_quarters_from_the_opening_end() -> None:
    lines = {
        "FY2026Q3": flows(30, 2, -3),
        "FY2026Q4": flows(40, 2, -3, change_receivables=-4),
        # the year holds its actual Q1-Q2 too: it must not be used for the stub
        "FY2026": flows(999, 99, -99),
        **{f"FY{y}": flows(100) for y in range(2027, 2031)},
    }
    out = quarter_forecast(lines)
    f = ValuationForecast(
        out, YEARS, {**{p.key: D("0.25") for p in out.periods}, "FY2026Q3": D("0.1")}
    )
    m = market(price_date=date(2026, 6, 30))
    details = _details(_dcf(_direct(), f, m))
    stub = details.periods[0]
    # Q3: 30 × 0.9 + 2 − 3 = 26; Q4: 40 × 0.75 + 2 − 3 − 4 = 25
    assert stub.stub is True
    assert (stub.period_key, stub.start, stub.end) == (
        "FY2026",
        date(2026, 7, 1),
        date(2026, 12, 31),
    )
    assert (stub.nopat, stub.d_and_a, stub.capex, stub.change_working_capital) == (
        D(57),
        D(4),
        D(-6),
        D(-4),
    )
    assert stub.fcff == D(51)
    assert stub.years == D(184) / YEAR
    second = details.periods[1]
    assert (second.stub, second.start, second.fcff) == (False, date(2027, 1, 1), D(75))


def test_the_valuation_date_is_the_opening_end_without_a_close() -> None:
    details = _details(_dcf(_direct(), m=market(price=None, price_date=None, bridge=_bridge())))
    assert details.valuation_date == FYE
    assert details.periods[0].years == D(365) / YEAR


def test_a_window_that_ended_before_the_valuation_date_is_not_discounted() -> None:
    m = market(price_date=date(2027, 3, 1), bridge=_bridge())
    first, second = _details(_dcf(_direct(), m=m)).periods[:2]
    assert (first.years, first.discount_factor, first.present_value) == (D(0), D(1), D(70))
    assert second.years == D(305) / YEAR  # 2027-03-01 → 2027-12-31
    mid = _details(_dcf(_direct(mid_year="true"), m=m)).periods
    assert mid[0].years == 0
    assert mid[1].years == D(305) / YEAR / 2  # midpoint of (v, e]


def _relative(a: Decimal | None, b: Decimal | None) -> Decimal:
    assert a is not None and b is not None
    return abs(a - b) / abs(b)


@pytest.mark.parametrize("mid_year", ["true", "false"])
def test_gordon_and_exit_value_alike_at_their_implied_counterparts(mid_year: str) -> None:
    gordon = _dcf(_direct(mid_year=mid_year, terminal_growth="0.03"))
    multiple = _details(gordon).terminal.implied_exit_multiple
    assert multiple is not None
    inputs = _direct(mid_year=mid_year, terminal_method="exit_multiple")
    exit_run = _dcf(inputs.with_values({"exit_multiple": multiple}))
    assert _relative(exit_run.enterprise_value, gordon.enterprise_value) <= D("1e-12")

    exit_at_10 = _dcf(
        _direct(mid_year=mid_year, terminal_method="exit_multiple", exit_multiple="10")
    )
    terminal = _details(exit_at_10).terminal
    assert (terminal.method, terminal.exit_multiple, terminal.growth) == (
        "exit_multiple",
        D(10),
        None,
    )
    assert terminal.value == D(1500)  # 10 × EBITDA_5
    growth = terminal.implied_growth
    assert growth is not None
    assert _close(growth, (D(1500) * D("0.1") - 100) / (1500 + 100))
    again = _dcf(_direct(mid_year=mid_year).with_values({"terminal_growth": growth}))
    assert _relative(again.enterprise_value, exit_at_10.enterprise_value) <= D("1e-12")


def test_constant_cash_flows_at_zero_growth_match_the_hand_sum() -> None:
    lines = {y: flows(100) for y in YEARS}  # FCFF = NOPAT = 100 at tax 0
    f = forecast(annual_forecast(lines))
    m = market(price_date=FYE)
    result = _dcf(_direct(terminal_growth="0"), f, m)
    taus = [D(d) / YEAR for d in END_DAYS]
    expected = sum((100 * D("1.1") ** -t for t in taus), D(0)) + D(1000) * D("1.1") ** -taus[-1]
    assert _close(result.enterprise_value, expected)


def test_sbc_is_not_added_back() -> None:
    with_sbc = _details(_dcf(_direct(), _five_years(sbc=50)))
    assert [p.fcff for p in with_sbc.periods] == FCFF


def test_a_null_line_counts_zero() -> None:
    lines = {y: {"operating_income": 100} for y in YEARS}
    details = _details(_dcf(_direct(), forecast(annual_forecast(lines))))
    assert details.periods[0].fcff == D(100)
    assert details.terminal.base_ebitda == D(100)


def _error(result: ValuationResult) -> str | None:
    assert (result.enterprise_value, result.equity_value, result.value_per_share) == (None,) * 3
    assert result.upside is None and result.details is None
    return result.error


def test_the_rate_must_exceed_terminal_growth() -> None:
    inputs = _direct(discount_rate="0.086", terminal_growth="0.09")
    assert _error(_dcf(inputs)) == "The discount rate (8.6%) must exceed terminal growth (9.0%)"
    equal = _direct(discount_rate="0.05", terminal_growth="0.05")
    assert _error(_dcf(equal)) == "The discount rate (5.0%) must exceed terminal growth (5.0%)"


def test_the_rate_must_be_positive() -> None:
    inputs = _inputs(risk_free_rate="0", beta="0", cost_of_debt="0", tax_rate="0", debt_weight="0")
    assert _error(_dcf(inputs)) == "The discount rate must be positive"


def test_wacc_needs_a_debt_weight() -> None:
    inputs = _inputs(cost_of_debt="0.05", tax_rate="0.2")
    assert inputs.get("debt_weight") is None
    assert _error(_dcf(inputs)) == NO_CLOSE


def test_wacc_needs_its_derived_inputs() -> None:
    assert _error(_dcf(_inputs(cost_of_debt="0.05", debt_weight="0.1"))) == "Set the tax rate"
    assert _error(_dcf(_inputs(tax_rate="0.2", debt_weight="0.1"))) == "Set the cost of debt"


def test_a_period_without_a_tax_rate_is_an_error() -> None:
    f = _five_years()
    rates = {k: v for k, v in f.tax_rates.items() if k != "FY2027"}
    result = _dcf(_direct(), ValuationForecast(f.statements, f.years, rates))
    assert _error(result) == "The forecast has no FY27E tax rate"


def test_no_share_count_leaves_the_value_per_share_null() -> None:
    for shares in (None, 0):
        result = _dcf(_direct(), m=market(shares=shares, bridge=_bridge()))
        assert result.error == "No share count"
        assert result.enterprise_value is not None and result.equity_value is not None
        assert result.value_per_share is None and result.upside is None
        assert result.details is not None


def test_no_price_leaves_the_upside_null() -> None:
    result = _dcf(_direct(), m=market(price=None, bridge=_bridge()))
    assert result.value_per_share is not None and result.upside is None


def test_implied_counterparts_and_terminal_share_are_null_when_not_meaningful() -> None:
    lines = {y: flows(-100, 10) for y in YEARS}  # EBITDA_5 = −90, FCFF = −90
    details = _details(_dcf(_direct(), forecast(annual_forecast(lines))))
    assert details.terminal.implied_exit_multiple is None
    assert details.terminal_share is None  # EV < 0
    exit_run = _details(
        _dcf(_direct(terminal_method="exit_multiple"), forecast(annual_forecast(lines)))
    )
    assert exit_run.terminal.implied_growth is None  # TV + FCFF_5 < 0
