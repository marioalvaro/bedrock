"""Ratios over the statement tables of one basis (docs/erd/analysis.md "Definitions (M2)"). Pure."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.mapping.config import parse_formula
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
from bedrock.statements.build import RATIO_PLACES, StatementTable
from bedrock.statements.periods import Period

RatioFreq = Literal["annual", "ttm"]

# Names resolve canonical code -> metric -> ratio (registry.py::validate).
_METRICS: dict[str, Metric] = {m.code: m for m in METRICS}

Point = tuple[int, str]  # (fiscal_year, fiscal_period): FY in annual, Q1..Q4 in TTM
Series = dict[Point, Decimal | None]


@dataclass(frozen=True)
class RatioInputs:
    """The untrimmed statement tables one ratio table reads, all of one basis.

    - `annual`: income/cash_flow/balance are the annual IS, CF and BS; `quarterly_income` is None.
    - `ttm`: income/cash_flow are the TTM IS and CF, balance is the quarterly BS, and
      `quarterly_income` is the quarterly IS (average-kind lines such as `shares_diluted` are empty
      in a TTM table: the latest quarter of the window that has a value is used)."""

    income: StatementTable
    cash_flow: StatementTable
    balance: StatementTable
    quarterly_income: StatementTable | None = None


@dataclass(frozen=True)
class RatioRow:
    code: str
    label: str
    category: Category
    unit: Unit
    definition: str
    caveat: str | None
    values: list[Decimal | None]  # aligned with RatioTable.periods; quantized to RATIO_PLACES


@dataclass(frozen=True)
class RatioTable:
    freq: RatioFreq
    periods: list[Period]
    rows: list[RatioRow]


def compute_ratios(
    inputs: RatioInputs,
    freq: RatioFreq,
    caveats: Sequence[Caveat] = (),
    ratios: Sequence[Ratio] = RATIOS,
) -> RatioTable:
    """Every ratio of `ratios`, in order, over the periods of `inputs.income`.

    Postconditions: one row per ratio; `values` aligned with `periods`; a period in which no ratio
    has a value is left out; a row's `caveat` is the text of the caveat whose codes contain it
    (None otherwise). Operand values, nulls and quantization follow the ERD. Raises ValueError when
    `freq` is `ttm` and `quarterly_income` is None; raises RegistryError when a custom `ratios`
    set (merged over `RATIOS` by code) fails `registry.validate`."""
    if freq == "ttm" and inputs.quarterly_income is None:
        raise ValueError("TTM ratios need the quarterly income statement")
    if tuple(ratios) != RATIOS:
        validate(METRICS, _merged(ratios), CANONICAL_CODES)
    evaluator = _Evaluator(inputs, freq, ratios)
    periods = inputs.income.periods
    grid = [
        [evaluator.ratio(ratio.code, (p.fiscal_year, p.fiscal_period)) for p in periods]
        for ratio in ratios
    ]
    kept = [i for i in range(len(periods)) if any(row[i] is not None for row in grid)]
    return RatioTable(
        freq=freq,
        periods=[periods[i] for i in kept],
        rows=[
            RatioRow(
                code=ratio.code,
                label=ratio.label,
                category=ratio.category,
                unit=ratio.unit,
                definition=ratio.definition,
                caveat=next((c.text for c in caveats if ratio.code in c.codes), None),
                values=[row[i] for i in kept],
            )
            for ratio, row in zip(ratios, grid, strict=True)
        ],
    )


def _merged(ratios: Sequence[Ratio]) -> tuple[Ratio, ...]:
    """`RATIOS` with `ratios` replacing or extending them by code (what the evaluator resolves)."""
    by_code = {r.code: r for r in RATIOS} | {r.code: r for r in ratios}
    return tuple(by_code.values())


def _series(tables: Sequence[StatementTable]) -> dict[str, tuple[str, Series]]:
    """code -> (kind, values by point); the first table holding a code wins."""
    found: dict[str, tuple[str, Series]] = {}
    for table in tables:
        points = [(p.fiscal_year, p.fiscal_period) for p in table.periods]
        for row in table.rows:
            if row.code not in found:
                found[row.code] = (row.kind, dict(zip(points, row.values, strict=True)))
    return found


def _quarter_back(point: Point) -> Point:
    """The quarter before `point` (Q1 -> Q4 of the year before)."""
    year, period = point
    q = int(period[1:])
    return (year - 1, "Q4") if q == 1 else (year, f"Q{q - 1}")


class _Evaluator:
    """Operand and ratio values at a point, memoized per (ratio code, point)."""

    def __init__(self, inputs: RatioInputs, freq: RatioFreq, ratios: Sequence[Ratio]) -> None:
        self._freq = freq
        self._lines = _series([inputs.income, inputs.cash_flow, inputs.balance])
        quarterly = inputs.quarterly_income
        self._quarterly = _series([quarterly]) if quarterly is not None else {}
        self._ratios = {r.code: r for r in _merged(ratios)}
        self._memo: dict[tuple[str, Point], Decimal | None] = {}

    def ratio(self, code: str, point: Point) -> Decimal | None:
        key = (code, point)
        if key not in self._memo:
            self._memo[key] = self._compute(self._ratios[code], point)
        return self._memo[key]

    def _compute(self, ratio: Ratio, point: Point) -> Decimal | None:
        numerator, denominator = ratio.numerator, ratio.denominator
        if self._freq == "ttm" and ratio.ttm is not None:
            numerator, denominator = ratio.ttm
        num = self._operand(numerator, point, ratio.avg_numerator)
        if num is None:
            return None
        if denominator is None:
            return (num * ratio.scale).quantize(RATIO_PLACES)
        den = self._operand(denominator, point, ratio.avg_denominator)
        if den is None or den <= 0:
            return None
        return (num / den * ratio.scale).quantize(RATIO_PLACES)

    def _operand(self, text: str, point: Point, average: bool) -> Decimal | None:
        current = self._formula(text, point)
        if not average:
            return current
        prior = self._formula(text, (point[0] - 1, point[1]))
        if current is None or prior is None:
            return None
        return (current + prior) / 2

    def _formula(self, text: str, point: Point) -> Decimal | None:
        total = Decimal(0)
        for sign, code in parse_formula(text):
            value = self._value(code, point)
            if value is None:
                return None
            total += sign * value
        return total

    def _value(self, code: str, point: Point) -> Decimal | None:
        if code in CANONICAL_CODES:
            return self._line(code, point)
        metric = _METRICS.get(code)
        if metric is not None:
            return metric.fn({name: self._value(name, point) for name in metric.inputs})
        return self.ratio(code, point)

    def _line(self, code: str, point: Point) -> Decimal | None:
        kind, values = self._lines.get(code, ("", {}))
        if self._freq == "ttm" and kind == "average":
            return self._latest_in_window(code, point)
        return values.get(point)

    def _latest_in_window(self, code: str, point: Point) -> Decimal | None:
        """The latest of the four quarters ending at `point` that has a value."""
        _, values = self._quarterly.get(code, ("", {}))
        quarter = point
        for _ in range(4):
            value = values.get(quarter)
            if value is not None:
                return value
            quarter = _quarter_back(quarter)
        return None
