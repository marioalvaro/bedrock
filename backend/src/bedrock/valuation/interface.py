"""What a valuation method takes and returns (docs/erd/valuation.md "Interface (orig. §6)"). Pure,
`Decimal` throughout, unrounded."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol

from bedrock.forecast.engines.driver import ForecastStatements
from bedrock.forecast.resolve import ResolvedDrivers

if TYPE_CHECKING:
    from bedrock.valuation.inputs import ResolvedInputs

ZERO = Decimal(0)
ReferenceSource = Literal["own_history", "peer_median"]


@dataclass(frozen=True)
class Bridge:
    """The claims between enterprise value and equity value, from the opening balance sheet."""

    total_debt: Decimal
    cash: Decimal
    short_term_investments: Decimal
    minority_interest: Decimal
    temporary_equity: Decimal

    @property
    def net_claims(self) -> Decimal:
        """EV − equity: debt + minority interest + temporary equity − cash − investments."""
        return (
            self.total_debt
            + self.minority_interest
            + self.temporary_equity
            - self.cash
            - self.short_term_investments
        )


@dataclass(frozen=True)
class MultipleReference:
    """A multiple target's reference multiple (own-history percentile or peer median), resolved
    by the service; `error` says why there is none."""

    value: Decimal | None
    source: ReferenceSource
    percentile: Decimal | None = None
    n: int | None = None
    comps_set: tuple[int, str] | None = None
    error: str | None = None


@dataclass(frozen=True)
class MarketData:
    price: Decimal | None
    price_date: date | None
    shares: Decimal | None
    bridge: Bridge
    references: Mapping[str, MultipleReference]  # by multiple target code (`pe`, …)


@dataclass(frozen=True)
class ValuationForecast:
    """A case's forecast, its forecast fiscal years and the resolved tax rate of every forecast
    period key (FY and quarter)."""

    statements: ForecastStatements
    years: tuple[int, ...]
    tax_rates: Mapping[str, Decimal]


@dataclass(frozen=True)
class DiscountDetails:
    method: str  # wacc | direct
    rate: Decimal
    cost_of_equity: Decimal | None = None
    after_tax_cost_of_debt: Decimal | None = None
    risk_free_rate: Decimal | None = None
    equity_risk_premium: Decimal | None = None
    beta: Decimal | None = None
    cost_of_debt: Decimal | None = None
    tax_rate: Decimal | None = None
    debt_weight: Decimal | None = None
    equity_weight: Decimal | None = None


@dataclass(frozen=True)
class DcfPeriod:
    period_key: str
    label: str
    start: date  # the window's first day
    end: date
    stub: bool
    nopat: Decimal
    d_and_a: Decimal
    change_working_capital: Decimal
    capex: Decimal
    fcff: Decimal
    years: Decimal  # τ, from the valuation date
    discount_factor: Decimal
    present_value: Decimal


@dataclass(frozen=True)
class TerminalDetails:
    method: str  # gordon | exit_multiple
    growth: Decimal | None  # set for gordon
    exit_multiple: Decimal | None  # set for exit_multiple
    base_fcff: Decimal
    base_ebitda: Decimal
    value: Decimal
    years: Decimal
    discount_factor: Decimal
    present_value: Decimal
    implied_exit_multiple: Decimal | None
    implied_growth: Decimal | None


@dataclass(frozen=True)
class DcfDetails:
    valuation_date: date
    discount: DiscountDetails
    mid_year: bool
    periods: tuple[DcfPeriod, ...]
    terminal: TerminalDetails
    sum_present_value: Decimal
    terminal_share: Decimal | None


@dataclass(frozen=True)
class MultipleDetails:
    ratio_code: str
    metric_label: str
    fiscal_year: int
    period_label: str
    metric_value: Decimal
    multiple: Decimal
    source: str  # manual | own_history | peer_median
    percentile: Decimal | None
    n: int | None
    comps_set: tuple[int, str] | None


@dataclass(frozen=True)
class ValuationResult:
    """One thing valued. A result whose inputs cannot produce a value has `error` (its numbers
    are then null where they cannot be computed); it never raises."""

    key: str
    method: str
    label: str
    enterprise_value: Decimal | None
    equity_value: Decimal | None
    value_per_share: Decimal | None
    upside: Decimal | None
    details: DcfDetails | MultipleDetails | None
    error: str | None = None


class ValuationMethod(Protocol):
    code: ClassVar[str]

    def value(
        self, forecast: ValuationForecast, market: MarketData, inputs: ResolvedInputs
    ) -> list[ValuationResult]:
        """One result per thing valued (multiples: per target)."""
        ...


def upside(value_per_share: Decimal | None, price: Decimal | None) -> Decimal | None:
    """value ÷ price − 1; null without a value or a positive price."""
    if value_per_share is None or price is None or price <= 0:
        return None
    return value_per_share / price - 1


def bridge_from_balance(balance: Mapping[str, Decimal]) -> Bridge:
    """The bridge of an opening balance sheet: debt = short + long term (finance leases included,
    operating leases not), minority interest = max(nci, 0); a missing line counts 0."""

    def line(code: str) -> Decimal:
        return balance.get(code, ZERO)

    return Bridge(
        total_debt=line("short_term_debt") + line("long_term_debt"),
        cash=line("cash"),
        short_term_investments=line("short_term_investments"),
        minority_interest=max(line("nci"), ZERO),
        temporary_equity=line("temporary_equity"),
    )


def valuation_forecast(
    statements: ForecastStatements, drivers: ResolvedDrivers
) -> ValuationForecast:
    """The forecast with its years (the resolution's) and each forecast period's resolved
    `tax_rate`; a period whose tax rate is not a number is left out."""
    rates: dict[str, Decimal] = {}
    for p in statements.periods:
        value = drivers.get("tax_rate", p.fiscal_year, p.fiscal_period).value
        if isinstance(value, Decimal):
            rates[p.key] = value
    return ValuationForecast(statements, drivers.years, rates)
