"""Multiple targets: a forecast metric × a multiple → an implied value per share
(docs/erd/valuation.md "Multiple targets (M5)"). Pure, `Decimal`, unrounded."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from bedrock.analysis.multiples import MIN_HISTORY
from bedrock.statements.periods import Period
from bedrock.valuation.inputs import TARGETS, ResolvedInputs
from bedrock.valuation.interface import (
    MarketData,
    MultipleDetails,
    MultipleReference,
    ValuationForecast,
    ValuationResult,
    upside,
)

ZERO = Decimal(0)
Metric = Callable[[ValuationForecast, Period], Decimal | None]


class _Failed(Exception):
    """A target that cannot produce a value; the message is the result's error."""


def _line(code: str) -> Metric:
    return lambda forecast, period: forecast.statements.get(code, period.key)


def _ebitda(forecast: ValuationForecast, period: Period) -> Decimal | None:
    operating = forecast.statements.get("operating_income", period.key)
    d_and_a = forecast.statements.get("d_and_a", period.key)
    return None if operating is None else operating + (d_and_a or ZERO)


@dataclass(frozen=True)
class TargetDef:
    code: str
    metric_label: str
    metric: Metric
    equity: bool  # an equity multiple (P/E, P/FCF); else an EV multiple


# In result order (ERD); labels from `inputs.TARGETS` (the ratio registry's).
TARGET_DEFS: tuple[TargetDef, ...] = (
    TargetDef("pe", "net income to common", _line("net_income_common"), equity=True),
    TargetDef("ev_ebitda", "EBITDA", _ebitda, equity=False),
    TargetDef("p_fcf", "free cash flow", _line("free_cash_flow"), equity=True),
    TargetDef("ev_sales", "revenue", _line("revenue"), equity=False),
)


def percentile(values: Sequence[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation over the sorted values v_0..v_{n−1} at position p × (n − 1).
    Raises ValueError for no values."""
    if not values:
        raise ValueError("No values")
    ordered = sorted(values)
    position = p * (len(ordered) - 1)
    low = int(position)
    if low >= len(ordered) - 1:
        return ordered[-1]
    return ordered[low] + (position - low) * (ordered[low + 1] - ordered[low])


def own_history_reference(
    values: Sequence[Decimal | None], p: Decimal, label: str
) -> MultipleReference:
    """The `p` percentile of a ratio's annual values, nulls and values ≤ 0 left out; an error
    with fewer than MIN_HISTORY values."""
    found = [v for v in values if v is not None and v > 0]
    if len(found) < MIN_HISTORY:
        return MultipleReference(
            None,
            "own_history",
            percentile=p,
            n=len(found),
            error=f"{label}: fewer than {MIN_HISTORY} years of history",
        )
    return MultipleReference(percentile(found, p), "own_history", percentile=p, n=len(found))


class MultipleTargets:
    code: ClassVar[str] = "multiple_target"

    def value(
        self, forecast: ValuationForecast, market: MarketData, inputs: ResolvedInputs
    ) -> list[ValuationResult]:
        """One result per target whose source is not `off`, in TARGET_DEFS order."""
        results = []
        for target in TARGET_DEFS:
            source = inputs.get(f"{target.code}_source")
            if source == "off":
                continue
            label = TARGETS[target.code][0]
            key = f"multiple:{target.code}"
            try:
                results.append(_value(target, str(source), forecast, market, inputs))
            except _Failed as failed:
                results.append(
                    ValuationResult(
                        key, self.code, label, None, None, None, None, None, str(failed)
                    )
                )
        return results


def _value(
    target: TargetDef,
    source: str,
    forecast: ValuationForecast,
    market: MarketData,
    inputs: ResolvedInputs,
) -> ValuationResult:
    label = TARGETS[target.code][0]
    year_index = inputs.get(f"{target.code}_year")
    if not isinstance(year_index, int) or not 1 <= year_index <= len(forecast.years):
        raise _Failed(f"{label}: no forecast year {year_index}")
    year = forecast.years[year_index - 1]
    period = next((p for p in forecast.statements.annual() if p.fiscal_year == year), None)
    if period is None:
        raise _Failed(f"{label}: no forecast year {year_index}")
    metric = target.metric(forecast, period)
    if metric is None or metric <= 0:
        raise _Failed(f"{period.label} {target.metric_label} is not positive")

    reference: MultipleReference | None = None
    if source == "manual":
        manual = inputs.get(f"{target.code}_multiple")
        if not isinstance(manual, Decimal):
            raise _Failed(f"Set the {label} multiple")
        multiple = manual
    else:
        reference = market.references.get(target.code)
        if reference is None:
            raise _Failed(f"{label}: no reference multiple")
        if reference.error is not None or reference.value is None:
            raise _Failed(reference.error or f"{label}: no reference multiple")
        multiple = reference.value
    if multiple <= 0:
        raise _Failed(f"{label}: the multiple is not positive")

    claims = market.bridge.net_claims
    if target.equity:
        equity = multiple * metric
        ev = equity + claims
    else:
        ev = multiple * metric
        equity = ev - claims
    shares = market.shares
    per_share = equity / shares if shares is not None and shares > 0 else None
    details = MultipleDetails(
        ratio_code=target.code,
        metric_label=target.metric_label,
        fiscal_year=year,
        period_label=period.label,
        metric_value=metric,
        multiple=multiple,
        source=source,
        percentile=None if reference is None else reference.percentile,
        n=None if reference is None else reference.n,
        comps_set=None if reference is None else reference.comps_set,
    )
    return ValuationResult(
        f"multiple:{target.code}",
        MultipleTargets.code,
        label,
        ev,
        equity,
        per_share,
        upside(per_share, market.price),
        details,
        None if per_share is not None else "No share count",
    )
