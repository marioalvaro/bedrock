"""DCF on FCFF (docs/erd/valuation.md "DCF on FCFF (M5)"). Pure, `Decimal`, unrounded."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar

from bedrock.statements.periods import Period
from bedrock.valuation.inputs import NO_CLOSE, ResolvedInputs, input_def
from bedrock.valuation.interface import (
    DcfDetails,
    DcfPeriod,
    DiscountDetails,
    MarketData,
    TerminalDetails,
    ValuationForecast,
    ValuationResult,
    upside,
)

ZERO, ONE = Decimal(0), Decimal(1)
YEAR_DAYS = Decimal("365.25")
WC_LINES = ("change_receivables", "change_inventory", "change_payables")
STUB_OPENINGS = ("Q1", "Q2", "Q3")
KEY, LABEL = "dcf_fcff", "DCF (FCFF)"


class _Failed(Exception):
    """A valuation that cannot produce a value; the message is the result's error."""


@dataclass(frozen=True)
class _Flows:
    nopat: Decimal
    d_and_a: Decimal
    change_working_capital: Decimal
    capex: Decimal

    @property
    def fcff(self) -> Decimal:
        return self.nopat + self.d_and_a + self.change_working_capital + self.capex


class DcfFcff:
    code: ClassVar[str] = "dcf_fcff"

    def value(
        self, forecast: ValuationForecast, market: MarketData, inputs: ResolvedInputs
    ) -> list[ValuationResult]:
        try:
            return [_value(forecast, market, inputs)]
        except _Failed as failed:
            return [
                ValuationResult(KEY, self.code, LABEL, None, None, None, None, None, str(failed))
            ]


def discount(inputs: ResolvedInputs) -> DiscountDetails:
    """The discount rate r: `direct` → `discount_rate`; `wacc` → (1 − w) k_e + w k_d (1 − t),
    k_e = r_f + β × ERP. Raises _Failed (no debt weight, a missing input, r ≤ 0)."""
    if inputs.get("discount_method") == "direct":
        details = DiscountDetails("direct", _number(inputs, "discount_rate"))
    else:
        if inputs.get("debt_weight") is None:
            raise _Failed(NO_CLOSE)
        risk_free = _number(inputs, "risk_free_rate")
        premium = _number(inputs, "equity_risk_premium")
        beta = _number(inputs, "beta")
        cost_of_debt = _number(inputs, "cost_of_debt")
        tax = _number(inputs, "tax_rate")
        weight = _number(inputs, "debt_weight")
        equity = risk_free + beta * premium
        debt = cost_of_debt * (1 - tax)
        details = DiscountDetails(
            method="wacc",
            rate=(1 - weight) * equity + weight * debt,
            cost_of_equity=equity,
            after_tax_cost_of_debt=debt,
            risk_free_rate=risk_free,
            equity_risk_premium=premium,
            beta=beta,
            cost_of_debt=cost_of_debt,
            tax_rate=tax,
            debt_weight=weight,
            equity_weight=1 - weight,
        )
    if details.rate <= 0:
        raise _Failed("The discount rate must be positive")
    return details


def _number(inputs: ResolvedInputs, code: str) -> Decimal:
    value = inputs.get(code)
    if not isinstance(value, Decimal):
        raise _Failed(f"Set the {input_def(code).label.lower()}")
    return value


def _value(
    forecast: ValuationForecast, market: MarketData, inputs: ResolvedInputs
) -> ValuationResult:
    rate_details = discount(inputs)
    r = rate_details.rate
    statements = forecast.statements
    opening = statements.opening.period
    annual = [p for p in statements.annual() if p.fiscal_year in forecast.years]
    if not annual:
        raise _Failed("The forecast has no forecast years")
    valued_at = market.price_date or opening.end
    mid_year = inputs.get("mid_year") is True

    def years(day: date) -> Decimal:
        return Decimal((day - valued_at).days) / YEAR_DAYS

    def factor(tau: Decimal) -> Decimal:
        return (1 + r) ** -tau

    periods: list[DcfPeriod] = []
    start = opening.end
    for index, period in enumerate(annual):
        stub = index == 0 and opening.fiscal_period in STUB_OPENINGS
        sources = (
            [
                q
                for q in statements.periods
                if q.fiscal_period != "FY" and q.fiscal_year == period.fiscal_year
            ]
            if stub
            else [period]
        )
        flows = _sum_flows([_flows(forecast, q) for q in sources])
        end = period.end
        tau = (years(max(start, valued_at)) + years(end)) / 2 if mid_year else years(end)
        tau = max(tau, ZERO)
        df = factor(tau)
        periods.append(
            DcfPeriod(
                period_key=period.key,
                label=period.label,
                start=start + timedelta(days=1),
                end=end,
                stub=stub,
                nopat=flows.nopat,
                d_and_a=flows.d_and_a,
                change_working_capital=flows.change_working_capital,
                capex=flows.capex,
                fcff=flows.fcff,
                years=tau,
                discount_factor=df,
                present_value=flows.fcff * df,
            )
        )
        start = end

    last = annual[-1]
    base_fcff = periods[-1].fcff
    base_ebitda = _line(forecast, "operating_income", last) + _line(forecast, "d_and_a", last)
    terminal_method = inputs.get("terminal_method")
    growth: Decimal | None = None
    multiple: Decimal | None = None
    if terminal_method == "exit_multiple":
        multiple = _number(inputs, "exit_multiple")
        tv = multiple * base_ebitda
    else:
        growth = _number(inputs, "terminal_growth")
        if r <= growth:
            raise _Failed(
                f"The discount rate ({_percent(r)}) must exceed terminal growth "
                f"({_percent(growth)})"
            )
        tv = base_fcff * (1 + growth) / (r - growth)
    tv_years = max(years(last.end), ZERO)
    tv_factor = factor(tv_years)
    pv_tv = tv * tv_factor
    terminal = TerminalDetails(
        method="exit_multiple" if multiple is not None else "gordon",
        growth=growth,
        exit_multiple=multiple,
        base_fcff=base_fcff,
        base_ebitda=base_ebitda,
        value=tv,
        years=tv_years,
        discount_factor=tv_factor,
        present_value=pv_tv,
        implied_exit_multiple=tv / base_ebitda if base_ebitda > 0 else None,
        implied_growth=(tv * r - base_fcff) / (tv + base_fcff) if tv + base_fcff > 0 else None,
    )
    sum_pv = sum((p.present_value for p in periods), ZERO)
    ev = sum_pv + pv_tv
    equity = ev - market.bridge.net_claims
    shares = market.shares
    per_share = equity / shares if shares is not None and shares > 0 else None
    details = DcfDetails(
        valuation_date=valued_at,
        discount=rate_details,
        mid_year=mid_year,
        periods=tuple(periods),
        terminal=terminal,
        sum_present_value=sum_pv,
        terminal_share=pv_tv / ev if ev > 0 else None,
    )
    return ValuationResult(
        KEY,
        DcfFcff.code,
        LABEL,
        ev,
        equity,
        per_share,
        upside(per_share, market.price),
        details,
        None if per_share is not None else "No share count",
    )


def _line(forecast: ValuationForecast, code: str, period: Period) -> Decimal:
    return forecast.statements.get(code, period.key) or ZERO


def _flows(forecast: ValuationForecast, period: Period) -> _Flows:
    """One period's FCFF lines: NOPAT = operating income × (1 − the period's tax rate), the CF
    lines in their displayed signs; a null line counts 0. SBC is not added back."""
    tax = forecast.tax_rates.get(period.key)
    if tax is None:
        raise _Failed(f"The forecast has no {period.label} tax rate")
    return _Flows(
        nopat=_line(forecast, "operating_income", period) * (1 - tax),
        d_and_a=_line(forecast, "d_and_a", period),
        change_working_capital=sum((_line(forecast, c, period) for c in WC_LINES), ZERO),
        capex=_line(forecast, "capex", period),
    )


def _sum_flows(parts: Sequence[_Flows]) -> _Flows:
    return _Flows(
        nopat=sum((p.nopat for p in parts), ZERO),
        d_and_a=sum((p.d_and_a for p in parts), ZERO),
        change_working_capital=sum((p.change_working_capital for p in parts), ZERO),
        capex=sum((p.capex for p in parts), ZERO),
    )


def _percent(rate: Decimal) -> str:
    return f"{rate * 100:.1f}%"
