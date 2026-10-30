"""The guidance log (FR-ANL-09): judging guidance ranges against actuals. Pure.

An entry guides one metric in one fiscal period on one basis. `evaluate` judges each entry against
the actual it is given, marks which entry of each (metric, period, basis) is the latest revision,
and `summarize` turns the results into the hit/miss record, counting the latest entries only.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from bedrock.statements.build import RATIO_PLACES

Basis = Literal["reported", "normalized"]
Direction = Literal["higher", "lower"]
Verdict = Literal["beat", "in_range", "miss", "pending"]

# Metrics where a smaller actual is the good outcome; every other metric defaults to `higher`.
LOWER_IS_BETTER = frozenset(
    {
        "cost_of_revenue",
        "total_operating_costs",
        "rnd",
        "sga",
        "other_operating_expenses",
        "interest_expense",
        "income_tax",
        "dso",
        "dio",
        "ccc",
        "debt_to_ebitda",
        "net_debt_to_ebitda",
        "debt_to_equity",
    }
)

# The ratios a quarter can be guided on: margins from that quarter's flows, as the canonical
# line codes that are summed for the numerator (the denominator is the quarter's revenue).
QUARTER_RATIOS: dict[str, tuple[str, ...]] = {
    "gross_margin": ("gross_profit",),
    "operating_margin": ("operating_income",),
    "ebitda_margin": ("operating_income", "d_and_a"),
    "net_margin": ("net_income_common",),
    "fcf_margin": ("free_cash_flow",),
}

# (basis, metric, fiscal_year, fiscal_period): where an entry's actual is looked up.
ActualKey = tuple[Basis, str, int, str]


@dataclass(frozen=True)
class GuidanceEntry:
    id: int
    metric: str
    fiscal_year: int
    fiscal_period: str  # FY | Q1..Q4
    low: Decimal
    high: Decimal
    basis: Basis
    direction: Direction
    given_on: date


@dataclass(frozen=True)
class GuidanceResult:
    entry: GuidanceEntry
    actual: Decimal | None
    verdict: Verdict
    surprise: Decimal | None  # (actual - midpoint) / |midpoint|, not flipped for `lower`
    latest: bool  # the last revision of its (metric, period, basis)


@dataclass(frozen=True)
class MetricSummary:
    metric: str
    beat: int
    in_range: int
    miss: int
    pending: int
    hit_rate: Decimal | None


@dataclass(frozen=True)
class GuidanceSummary:
    beat: int
    in_range: int
    miss: int
    pending: int
    hit_rate: Decimal | None  # (beat + in_range) / (beat + in_range + miss)
    by_metric: list[MetricSummary]  # by metric code


def evaluate(
    entries: Sequence[GuidanceEntry], actuals: Mapping[ActualKey, Decimal | None]
) -> list[GuidanceResult]:
    """One result per entry, in the order given. An entry whose key is not in `actuals` (or is
    None there) is pending. Among entries with the same (metric, fiscal_year, fiscal_period,
    basis) the latest `given_on` is the latest revision (ties: the highest id)."""
    newest: dict[tuple[str, int, str, str], tuple[date, int]] = {}
    for e in entries:
        key = (e.metric, e.fiscal_year, e.fiscal_period, e.basis)
        newest[key] = max(newest.get(key, (e.given_on, e.id)), (e.given_on, e.id))
    return [
        _judge(
            e,
            actuals.get((e.basis, e.metric, e.fiscal_year, e.fiscal_period)),
            newest[(e.metric, e.fiscal_year, e.fiscal_period, e.basis)] == (e.given_on, e.id),
        )
        for e in entries
    ]


def summarize(results: Iterable[GuidanceResult]) -> GuidanceSummary:
    """The record of the latest entries: verdict counts overall and per metric."""
    latest = [r for r in results if r.latest]
    by_metric = [
        _tally(metric, [r for r in latest if r.entry.metric == metric])
        for metric in sorted({r.entry.metric for r in latest})
    ]
    total = _tally("", latest)
    return GuidanceSummary(
        total.beat, total.in_range, total.miss, total.pending, total.hit_rate, by_metric
    )


def quarter_margin(code: str, quarter_values: Mapping[str, Decimal | None]) -> Decimal | None:
    """A margin of one quarter: the sum of its numerator lines over the quarter's revenue,
    quantized to 6 places. None when revenue is missing or not positive, or when any numerator
    line is missing. Raises ValueError for a ratio that is not in `QUARTER_RATIOS`."""
    operands = QUARTER_RATIOS.get(code)
    if operands is None:
        raise ValueError(
            f"{code} cannot be guided on a quarter: use one of {sorted(QUARTER_RATIOS)}"
        )
    revenue = quarter_values.get("revenue")
    parts = [quarter_values.get(c) for c in operands]
    if revenue is None or revenue <= 0 or any(p is None for p in parts):
        return None
    return (sum((p for p in parts if p is not None), Decimal(0)) / revenue).quantize(RATIO_PLACES)


def _judge(entry: GuidanceEntry, actual: Decimal | None, latest: bool) -> GuidanceResult:
    if actual is None:
        return GuidanceResult(entry, None, "pending", None, latest)
    above, below = actual > entry.high, actual < entry.low
    if entry.direction == "lower":
        above, below = below, above
    verdict: Verdict = "beat" if above else "miss" if below else "in_range"
    midpoint = (entry.low + entry.high) / 2
    surprise = (
        None if midpoint == 0 else ((actual - midpoint) / abs(midpoint)).quantize(RATIO_PLACES)
    )
    return GuidanceResult(entry, actual, verdict, surprise, latest)


def _tally(metric: str, results: Sequence[GuidanceResult]) -> MetricSummary:
    counts = {
        v: sum(1 for r in results if r.verdict == v)
        for v in ("beat", "in_range", "miss", "pending")
    }
    decided = counts["beat"] + counts["in_range"] + counts["miss"]
    hit_rate = (
        None
        if decided == 0
        else (Decimal(counts["beat"] + counts["in_range"]) / decided).quantize(RATIO_PLACES)
    )
    return MetricSummary(
        metric, counts["beat"], counts["in_range"], counts["miss"], counts["pending"], hit_rate
    )
