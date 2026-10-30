"""Ratio cell details: the formula and inputs behind one ratio value (docs/erd/analysis.md "Ratio
cell details"). Pure.

The values come from `calculator.Operands`, the reader that computed the ratio table, so an
explanation cannot disagree with the table.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Literal

from bedrock.mapping.config import CanonicalItemDef, load_canonical_items, parse_formula
from bedrock.ratios.calculator import Operands, Point, RatioFreq, RatioInputs, year_earlier
from bedrock.ratios.caveats import Caveat
from bedrock.ratios.registry import (
    CANONICAL_CODES,
    METRICS,
    RATIOS,
    Category,
    Metric,
    Ratio,
    Unit,
    validate,
)

TermKind = Literal["line", "metric", "ratio"]

_METRICS: dict[str, Metric] = {m.code: m for m in METRICS}
_METRIC_UNITS = {"price": "USD/shares", "tax_rate": "pct", "earnings_growth": "points"}
_WINDOW_NOTE = "latest quarter of the window with a value"


@dataclass(frozen=True)
class Term:
    """One input: a statement line, a metric (with its own inputs as `children`) or a ratio.
    `sign` is its sign in the operand's formula; `value` is unsigned."""

    code: str
    label: str
    kind: TermKind
    unit: str
    sign: int
    value: Decimal | None
    definition: str
    note: str | None
    children: tuple["Term", ...]


@dataclass(frozen=True)
class OperandExplanation:
    text: str  # the operand as written: "nopat", "total_debt - cash"
    average: bool
    value: Decimal | None  # the operand's value; the mean of both ends when `average`
    terms: tuple[Term, ...]
    prior_terms: tuple[Term, ...]  # the same terms a year earlier, only when `average`


@dataclass(frozen=True)
class RatioExplanation:
    code: str
    label: str
    category: Category
    unit: Unit
    definition: str
    caveat: str | None
    fiscal_year: int
    fiscal_period: str
    value: Decimal | None
    scale: Decimal
    numerator: OperandExplanation
    denominator: OperandExplanation | None
    reason: str | None  # why `value` is empty


@cache
def _items() -> dict[str, CanonicalItemDef]:
    return {i.code: i for i in load_canonical_items()}


def explain_ratio(
    inputs: RatioInputs,
    freq: RatioFreq,
    code: str,
    point: Point,
    caveats: Sequence[Caveat] = (),
    ratios: Sequence[Ratio] = RATIOS,
) -> RatioExplanation:
    """How the ratio `code` at `point` (fiscal year, FY or the quarter a TTM window ends at) was
    computed. Raises KeyError for an unknown ratio code or a period outside `inputs`."""
    if tuple(ratios) != RATIOS:
        validate(METRICS, tuple({r.code: r for r in (*RATIOS, *ratios)}.values()), CANONICAL_CODES)
    ops = Operands(inputs, freq, ratios)
    ratio = ops.definition(code)
    if not ops.has_period(point):
        raise KeyError(point)
    numerator_text, denominator_text = ops.operands_of(ratio)
    numerator = _operand(ops, freq, numerator_text, ratio.avg_numerator, point)
    denominator = (
        None
        if denominator_text is None
        else _operand(ops, freq, denominator_text, ratio.avg_denominator, point)
    )
    return RatioExplanation(
        code=ratio.code,
        label=ratio.label,
        category=ratio.category,
        unit=ratio.unit,
        definition=ratio.definition,
        caveat=next((c.text for c in caveats if ratio.code in c.codes), None),
        fiscal_year=point[0],
        fiscal_period=point[1],
        value=ops.ratio(code, point),
        scale=ratio.scale,
        numerator=numerator,
        denominator=denominator,
        reason=_reason(ops.ratio(code, point), numerator, denominator),
    )


def _reason(
    value: Decimal | None, numerator: OperandExplanation, denominator: OperandExplanation | None
) -> str | None:
    if value is not None:
        return None
    if numerator.value is None:
        return "numerator missing"
    if denominator is None:
        return None
    if denominator.value is None:
        return "denominator missing"
    return "denominator ≤ 0"


def _operand(
    ops: Operands, freq: RatioFreq, text: str, average: bool, point: Point
) -> OperandExplanation:
    return OperandExplanation(
        text=text,
        average=average,
        value=ops.operand(text, point, average),
        terms=_terms(ops, freq, text, point),
        prior_terms=_terms(ops, freq, text, year_earlier(point)) if average else (),
    )


def _terms(ops: Operands, freq: RatioFreq, text: str, point: Point) -> tuple[Term, ...]:
    return tuple(_term(ops, freq, code, sign, point) for sign, code in parse_formula(text))


def _term(
    ops: Operands, freq: RatioFreq, code: str, sign: int, point: Point, note: str | None = None
) -> Term:
    value = ops.value(code, point)
    if code in CANONICAL_CODES:
        item = _items()[code]
        window = _WINDOW_NOTE if freq == "ttm" and item.kind == "average" else None
        return Term(code, item.label, "line", item.unit, sign, value, "", note or window, ())
    metric = _METRICS.get(code)
    if metric is not None:
        return Term(
            code,
            metric.label,
            "metric",
            _METRIC_UNITS.get(code, "USD"),
            sign,
            value,
            metric.definition,
            note or _price_note(ops, point) if code == "price" else note,
            _children(ops, freq, metric, point),
        )
    ratio = ops.definition(code)
    return Term(code, ratio.label, "ratio", ratio.unit, sign, value, ratio.definition, note, ())


def _children(ops: Operands, freq: RatioFreq, metric: Metric, point: Point) -> tuple[Term, ...]:
    if metric.code == "earnings_growth":
        return (
            _term(ops, freq, "net_income_common", 1, point),
            _term(ops, freq, "net_income_common", 1, year_earlier(point), "a year earlier"),
        )
    return tuple(_term(ops, freq, name, 1, point) for name in metric.inputs)


def _price_note(ops: Operands, point: Point) -> str | None:
    close = ops.price_close(point)
    end = ops.period_end(point)
    if close is None or end is None:
        return None
    return (
        f"close of {close[0].isoformat()}, the last on or before the period end {end.isoformat()}"
    )
