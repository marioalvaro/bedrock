"""The driver catalog (docs/erd/forecasting.md "Drivers (M4)"). Pure.

Each driver has a history rule (how its value is read from an actual fiscal year), a fallback
(what a forecast year gets when the history gives no default) and bounds. All drivers are annual.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

Unit = Literal["pct", "days", "USD"]
DriverKind = Literal["value", "offset"]
RevenueMethod = Literal["growth", "segments", "volume_price"]
METHODS: tuple[RevenueMethod, ...] = ("growth", "segments", "volume_price")
SEGMENT_PREFIX = "segment_growth:"
AMOUNT_LIMIT = Decimal(10) ** 15  # services/adjustments.py::AMOUNT_LIMIT (G21)


class UnknownDriver(ValueError):
    """A driver code that is not in the catalog."""


# History rules: how a driver's value is read from fiscal year t of the normalized statements.
@dataclass(frozen=True)
class Growth:
    """code_t / code_{t-1} - 1."""

    code: str


@dataclass(frozen=True)
class SeriesGrowth:
    """A segment or KPI series' FY value_t / value_{t-1} - 1; the series comes from the scenario's
    settings (the segment id of the code, `volume_kpi` or `price_kpi`)."""

    series: Literal["segment", "volume", "price"]


@dataclass(frozen=True)
class Ratio:
    """sign × numerator / denominator. `positive_denominator`: null unless the denominator is > 0;
    `mean_denominator`: the denominator is the mean of its t-1 and t values."""

    numerator: str
    denominator: str
    sign: int = 1
    positive_denominator: bool = False
    mean_denominator: bool = False


@dataclass(frozen=True)
class Days:
    """numerator / denominator × days(t)."""

    numerator: str
    denominator: str


@dataclass(frozen=True)
class Amount:
    """sign × code (a cash-flow line, displayed sign)."""

    code: str
    sign: int = 1


HistoryRule = Growth | SeriesGrowth | Ratio | Days | Amount | None  # None: a policy, no history


@dataclass(frozen=True)
class Follows:
    """The fallback is another driver's value for the year: its resolved value (`resolved`), or
    else its default."""

    code: str
    resolved: bool


# required: no default and no set value makes the forecast unavailable; zero: 0; flat: the line
# is held at its opening value.
Fallback = Literal["required", "zero", "flat"] | Follows


@dataclass(frozen=True)
class Bounds:
    low: Decimal
    high: Decimal
    low_open: bool = False
    high_open: bool = False

    def contains(self, value: Decimal) -> bool:
        above = value > self.low if self.low_open else value >= self.low
        below = value < self.high if self.high_open else value <= self.high
        return above and below

    def __str__(self) -> str:
        high = "10^15" if self.high == AMOUNT_LIMIT else _plain(self.high)
        return (
            f"{'(' if self.low_open else '['}{_plain(self.low)}, {high}"
            f"{')' if self.high_open else ']'}"
        )


@dataclass(frozen=True)
class DriverDef:
    code: str
    label: str
    group: str
    unit: Unit
    history: HistoryRule
    fallback: Fallback
    bounds: Bounds
    methods: tuple[RevenueMethod, ...] = METHODS  # the revenue methods it applies to


GROWTH = Bounds(Decimal(-1), Decimal(10), low_open=True)
SHARE = Bounds(Decimal(0), Decimal(1))
SIGNED = Bounds(Decimal(-1), Decimal(1))
DAYS = Bounds(Decimal(0), Decimal(730))
AMOUNT = Bounds(Decimal(0), AMOUNT_LIMIT, high_open=True)
OFFSET_BOUNDS: dict[Unit, Bounds] = {
    "pct": SIGNED,
    "days": Bounds(Decimal(-730), Decimal(730)),
    "USD": Bounds(-AMOUNT_LIMIT, AMOUNT_LIMIT, low_open=True, high_open=True),
}

DRIVERS: tuple[DriverDef, ...] = (
    DriverDef(
        "revenue_growth",
        "Revenue growth",
        "Revenue",
        "pct",
        Growth("revenue"),
        "required",
        GROWTH,
        ("growth",),
    ),
    # A template: `drivers_for` expands it to one `segment_growth:<series id>` per series.
    DriverDef(
        "segment_growth",
        "Segment growth",
        "Revenue",
        "pct",
        SeriesGrowth("segment"),
        Follows("revenue_growth", resolved=False),
        GROWTH,
        ("segments",),
    ),
    DriverDef(
        "volume_growth",
        "Volume growth",
        "Revenue",
        "pct",
        SeriesGrowth("volume"),
        "zero",
        GROWTH,
        ("volume_price",),
    ),
    DriverDef(
        "price_growth",
        "Price growth",
        "Revenue",
        "pct",
        SeriesGrowth("price"),
        "zero",
        GROWTH,
        ("volume_price",),
    ),
    DriverDef(
        "gross_margin",
        "Gross margin",
        "Costs",
        "pct",
        Ratio("gross_profit", "revenue"),
        "required",
        SIGNED,
    ),
    DriverDef(
        "rnd_pct_revenue", "R&D % revenue", "Costs", "pct", Ratio("rnd", "revenue"), "zero", SHARE
    ),
    DriverDef(
        "sga_pct_revenue", "SG&A % revenue", "Costs", "pct", Ratio("sga", "revenue"), "zero", SHARE
    ),
    DriverDef(
        "other_opex_pct_revenue",
        "Other opex % revenue",
        "Costs",
        "pct",
        Ratio("other_operating_expenses", "revenue"),
        "zero",
        SIGNED,
    ),
    DriverDef(
        "d_and_a_pct_revenue",
        "D&A % revenue",
        "Costs",
        "pct",
        Ratio("d_and_a", "revenue"),
        Follows("capex_pct_revenue", resolved=True),
        SHARE,
    ),
    DriverDef(
        "sbc_pct_revenue", "SBC % revenue", "Costs", "pct", Ratio("sbc", "revenue"), "zero", SHARE
    ),
    DriverDef(
        "other_nonoperating_pct_revenue",
        "Other non-operating % revenue",
        "Below the line",
        "pct",
        Ratio("other_nonoperating_income", "revenue"),
        "zero",
        SIGNED,
    ),
    DriverDef(
        "interest_rate",
        "Interest rate",
        "Below the line",
        "pct",
        Ratio("interest_expense", "total_debt", mean_denominator=True),
        "zero",
        SHARE,
    ),
    DriverDef(
        "tax_rate",
        "Tax rate",
        "Below the line",
        "pct",
        Ratio("income_tax", "pretax_income", positive_denominator=True),
        "required",
        SHARE,
    ),
    DriverDef(
        "nci_share",
        "NCI share of net income",
        "Below the line",
        "pct",
        Ratio("net_income_nci", "net_income", positive_denominator=True),
        "zero",
        SHARE,
    ),
    DriverDef(
        "receivable_days",
        "Receivable days",
        "Working capital",
        "days",
        Days("receivables", "revenue"),
        "flat",
        DAYS,
    ),
    DriverDef(
        "inventory_days",
        "Inventory days",
        "Working capital",
        "days",
        Days("inventory", "cost_of_revenue"),
        "flat",
        DAYS,
    ),
    DriverDef(
        "payable_days",
        "Payable days",
        "Working capital",
        "days",
        Days("accounts_payable", "cost_of_revenue"),
        "flat",
        DAYS,
    ),
    DriverDef(
        "capex_pct_revenue",
        "Capex % revenue",
        "Investment",
        "pct",
        Ratio("capex", "revenue", sign=-1),
        "required",
        SHARE,
    ),
    DriverDef(
        "debt_issued", "Debt issued", "Financing", "USD", Amount("debt_issued"), "zero", AMOUNT
    ),
    DriverDef(
        "debt_repaid",
        "Debt repaid",
        "Financing",
        "USD",
        Amount("debt_repaid", sign=-1),
        "zero",
        AMOUNT,
    ),
    DriverDef("min_cash", "Minimum cash", "Financing", "USD", None, "zero", AMOUNT),
    DriverDef(
        "buybacks", "Buybacks", "Shareholders", "USD", Amount("buybacks", sign=-1), "zero", AMOUNT
    ),
    DriverDef(
        "dividend_payout",
        "Dividend payout",
        "Shareholders",
        "pct",
        Ratio("dividends_paid", "net_income_common", sign=-1, positive_denominator=True),
        "zero",
        Bounds(Decimal(0), Decimal(5)),
    ),
    DriverDef(
        "share_change",
        "Diluted share change",
        "Shareholders",
        "pct",
        Growth("shares_diluted"),
        "zero",
        Bounds(Decimal(-1), Decimal(1), low_open=True),
    ),
)
_BY_CODE = {d.code: d for d in DRIVERS}


def segment_code(series_id: int) -> str:
    return f"{SEGMENT_PREFIX}{series_id}"


def segment_id(code: str) -> int | None:
    """The series id of a `segment_growth:<id>` code; None for any other code."""
    if not code.startswith(SEGMENT_PREFIX):
        return None
    rest = code[len(SEGMENT_PREFIX) :]
    return int(rest) if rest.isascii() and rest.isdecimal() else None


def driver_def(code: str, label: str | None = None) -> DriverDef:
    """The catalog entry of a code; a `segment_growth:<id>` code gets the segment template with
    that code (and `label`, if given). Raises UnknownDriver."""
    if segment_id(code) is not None:
        template = _BY_CODE["segment_growth"]
        return replace(template, code=code, label=label or template.label)
    if code == "segment_growth" or code not in _BY_CODE:
        raise UnknownDriver(f"Unknown driver '{code}'")
    return _BY_CODE[code]


def drivers_for(method: RevenueMethod, segments: Sequence[tuple[int, str]] = ()) -> list[DriverDef]:
    """The drivers of a revenue method in catalog order; for `segments`, one segment growth per
    (series id, name) in the given order."""
    drivers: list[DriverDef] = []
    for d in DRIVERS:
        if method not in d.methods:
            continue
        if d.code == "segment_growth":
            drivers.extend(driver_def(segment_code(i), f"{name} growth") for i, name in segments)
        else:
            drivers.append(d)
    return drivers


def check_bounds(code: str, kind: DriverKind, value: Decimal) -> str | None:
    """None when `value` is allowed for the driver as a `value` or an `offset`, else the message.
    Raises UnknownDriver."""
    d = driver_def(code)
    name = f"{code} offset" if kind == "offset" else code
    if not value.is_finite():
        return f"{name} must be a finite number"
    bounds = OFFSET_BOUNDS[d.unit] if kind == "offset" else d.bounds
    return None if bounds.contains(value) else f"{name} must be in {bounds}"


def _plain(value: Decimal) -> str:
    return format(value, "f")
