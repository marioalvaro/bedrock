"""Ratios over the statement tables of one basis (docs/erd/analysis.md "Definitions (M2)"). Pure."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
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
from bedrock.statements.build import RATIO_PLACES, Row, StatementTable
from bedrock.statements.periods import Period, Point

RatioFreq = Literal["annual", "ttm"]

# Names resolve canonical code -> metric -> ratio (registry.py::validate).
_METRICS: dict[str, Metric] = {m.code: m for m in METRICS}

Series = dict[Point, Decimal | None]


@dataclass(frozen=True)
class RatioInputs:
    """The untrimmed statement tables one ratio table reads, all of one basis.

    - `annual`: income/cash_flow/balance are the annual IS, CF and BS; `quarterly_income` is None.
    - `ttm`: income/cash_flow are the TTM IS and CF, balance is the quarterly BS, and
      `quarterly_income` is the quarterly IS (average-kind lines such as `shares_diluted` are empty
      in a TTM table: the latest quarter of the window that has a value is used).
    - `prices`: `(date, close)` pairs, oldest first (`price_daily.close`, split-adjusted); a
      period's price is the last close on or before its end date, except that with `as_of` the
      latest period of `income` reads the last close on or before `as_of` (the current multiple)."""

    income: StatementTable
    cash_flow: StatementTable
    balance: StatementTable
    quarterly_income: StatementTable | None = None
    prices: Sequence[tuple[date, Decimal]] = ()
    as_of: date | None = None


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
    evaluator = Operands(inputs, freq, ratios)
    periods = inputs.income.periods
    grid = [[evaluator.ratio(ratio.code, p.point) for p in periods] for ratio in ratios]
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
                caveat=row_caveat(evaluator, ratio, caveats),
                values=[row[i] for i in kept],
            )
            for ratio, row in zip(ratios, grid, strict=True)
        ],
    )


def row_caveat(ops: "Operands", ratio: Ratio, caveats: Sequence[Caveat]) -> str | None:
    """A ratio row's caveat: the company's text from `caveats.yaml`, then the generated text for
    an operand line that holds or sits inside a combined line (M7b S4)."""
    texts = [
        next((c.text for c in caveats if ratio.code in c.codes), None),
        generated_caveat(ops.combined_operands(ratio)),
    ]
    return " ".join(t for t in texts if t) or None


def generated_caveat(includes: Mapping[str, Sequence[str]]) -> str | None:
    """ "<label> includes <labels>." for each carrier line, by label; a carrier whose combined
    concept covers no canonical row "includes other lines reported with it"."""
    sentences = []
    for carrier, covered in includes.items():
        if not covered:
            sentences.append(f"{carrier} includes other lines reported with it.")
        elif len(covered) == 1:
            sentences.append(f"{carrier} includes {covered[0]}.")
        else:
            sentences.append(f"{carrier} includes {', '.join(covered[:-1])} and {covered[-1]}.")
    return " ".join(sentences) or None


def _merged(ratios: Sequence[Ratio]) -> tuple[Ratio, ...]:
    """`RATIOS` with `ratios` replacing or extending them by code (what the evaluator resolves)."""
    by_code = {r.code: r for r in RATIOS} | {r.code: r for r in ratios}
    return tuple(by_code.values())


def _series(tables: Sequence[StatementTable]) -> dict[str, tuple[str, Series]]:
    """code -> (kind, values by point); the first table holding a code wins."""
    found: dict[str, tuple[str, Series]] = {}
    for table in tables:
        points = [p.point for p in table.periods]
        for row in table.rows:
            if row.code not in found:
                found[row.code] = (row.kind, dict(zip(points, row.values, strict=True)))
    return found


def _carriers(tables: Sequence[StatementTable]) -> dict[str, dict[Point, str]]:
    """code -> the carrier whose combined value holds the line's amount, by point (the cells
    marked `included_in`); the first table holding a code wins, as in `_series`."""
    found: dict[str, dict[Point, str]] = {}
    for table in tables:
        points = [p.point for p in table.periods]
        for row in table.rows:
            if row.code not in found:
                marks = zip(points, row.included_in, strict=True)
                found[row.code] = {point: carrier for point, carrier in marks if carrier}
    return found


def _quarter_back(point: Point) -> Point:
    """The quarter before `point` (Q1 -> Q4 of the year before)."""
    year, period = point
    q = int(period[1:])
    return (year - 1, "Q4") if q == 1 else (year, f"Q{q - 1}")


def year_earlier(point: Point) -> Point:
    """The same period a year earlier: FY2023 for FY2024, Q2 FY2023 for Q2 FY2024."""
    return (point[0] - 1, point[1])


class Operands:
    """Operand, metric and ratio values of one `RatioInputs` at a point, by the ERD's operand rules
    (annual: FY values and FY-end instants; ttm: TTM flows, quarter-end instants, average-kind
    lines from the latest quarter of the window). Ratio values are memoized per (code, point).
    Shared by the ratio calculator and the analysis engines (`analysis/qoe.py`,
    `analysis/capital_allocation.py`)."""

    def __init__(
        self, inputs: RatioInputs, freq: RatioFreq, ratios: Sequence[Ratio] = RATIOS
    ) -> None:
        self._freq = freq
        self._lines = _series([inputs.income, inputs.cash_flow, inputs.balance])
        self._carriers = _carriers([inputs.income, inputs.cash_flow, inputs.balance])
        self._rows: dict[str, Row] = {}
        for table in (inputs.income, inputs.cash_flow, inputs.balance, inputs.quarterly_income):
            for row in table.rows if table is not None else ():
                self._rows.setdefault(row.code, row)
        quarterly = inputs.quarterly_income
        self._quarterly = _series([quarterly]) if quarterly is not None else {}
        self._ratios = {r.code: r for r in _merged(ratios)}
        self._ends = {p.point: p.end for p in inputs.income.periods}
        self._prices = sorted(inputs.prices)
        if inputs.as_of is not None and inputs.income.periods:
            last = inputs.income.periods[-1]
            self._ends[last.point] = inputs.as_of
        self._memo: dict[tuple[str, Point], Decimal | None] = {}

    def ratio(self, code: str, point: Point) -> Decimal | None:
        key = (code, point)
        if key not in self._memo:
            self._memo[key] = self._compute(self._ratios[code], point)
        return self._memo[key]

    def definition(self, code: str) -> Ratio:
        """The ratio `code` (KeyError when there is none)."""
        return self._ratios[code]

    def has_period(self, point: Point) -> bool:
        return point in self._ends

    def operands_of(self, ratio: Ratio) -> tuple[str, str | None]:
        """The numerator and denominator this frequency reads (TTM may replace both)."""
        if self._freq == "ttm" and ratio.ttm is not None:
            return ratio.ttm
        return ratio.numerator, ratio.denominator

    def line_codes(self, ratio: Ratio) -> list[str]:
        """The canonical lines `ratio` reads at this frequency, through its metrics and the
        ratios it is built from, each once, in the order met."""
        found: dict[str, None] = {}
        pending = [t for t in self.operands_of(ratio) if t is not None]
        seen: set[str] = set()
        while pending:
            for _, code in parse_formula(pending.pop(0)):
                if code in seen:
                    continue
                seen.add(code)
                if code in CANONICAL_CODES:
                    found[code] = None
                elif (metric := _METRICS.get(code)) is not None:
                    pending.extend(metric.inputs)
                elif code in self._ratios:
                    pending.extend(t for t in self.operands_of(self._ratios[code]) if t is not None)
        return list(found)

    def combined_operands(self, ratio: Ratio) -> dict[str, tuple[str, ...]]:
        """By carrier label, the labels of the lines inside it, for every operand line of `ratio`
        that holds a combined value, or whose amount is inside one, in any period of the inputs."""
        includes: dict[str, dict[str, None]] = {}
        for code in self.line_codes(ratio):
            row = self._rows.get(code)
            if row is None:
                continue
            for codes in row.combined_with:
                if codes is not None:
                    inner = includes.setdefault(self._label(code), {})
                    inner.update((self._label(c), None) for c in codes)
            for carrier in row.included_in:
                if carrier is not None:
                    includes.setdefault(self._label(carrier), {})[row.label] = None
        return {carrier: tuple(inner) for carrier, inner in includes.items()}

    def _label(self, code: str) -> str:
        row = self._rows.get(code)
        return code if row is None else row.label

    def _compute(self, ratio: Ratio, point: Point) -> Decimal | None:
        numerator, denominator = self.operands_of(ratio)
        num = self.operand(numerator, point, ratio.avg_numerator)
        if num is None:
            return None
        if denominator is None:
            return (num * ratio.scale).quantize(RATIO_PLACES)
        den = self.operand(denominator, point, ratio.avg_denominator)
        if den is None or den <= 0:
            return None
        return (num / den * ratio.scale).quantize(RATIO_PLACES)

    def operand(self, text: str, point: Point, average: bool = False) -> Decimal | None:
        """A code or `+`/`-` formula at `point` (None when any term is None, except a line whose
        amount is inside a combined line that is a term of the same sign: it counts 0, as in the
        statement formulas, M7b S4); with `average`, the mean of it at `point` and a year earlier
        (None unless both exist)."""
        current = self._formula(text, point)
        if not average:
            return current
        prior = self._formula(text, year_earlier(point))
        if current is None or prior is None:
            return None
        return (current + prior) / 2

    def _formula(self, text: str, point: Point) -> Decimal | None:
        terms = parse_formula(text)
        total = Decimal(0)
        for sign, code in terms:
            value = self.value(code, point)
            if value is None:
                # the carrier's value already holds a covered line's amount
                if (sign, self._carrier(code, point)) not in terms:
                    return None
                continue
            total += sign * value
        return total

    def _carrier(self, code: str, point: Point) -> str | None:
        """The line that holds `code`'s amount at `point` (a combined line), if any."""
        return self._carriers.get(code, {}).get(point)

    def _metric_inputs(self, metric: Metric, point: Point) -> dict[str, Decimal | None]:
        """A metric's input values; an empty input whose amount is inside another input (a
        combined line) is 0, so the metric does not count it twice or go empty. A metric never
        takes a carrier and its covered line with opposite signs."""
        values = {name: self.value(name, point) for name in metric.inputs}
        for name, value in values.items():
            if value is None and self._carrier(name, point) in metric.inputs:
                values[name] = Decimal(0)
        return values

    def value(self, code: str, point: Point) -> Decimal | None:
        """One canonical, metric or ratio code at `point` (unquantized for lines and metrics)."""
        if code in CANONICAL_CODES:
            return self._line(code, point)
        metric = _METRICS.get(code)
        if metric is not None and metric.at_point:
            return self._at_point(code, point)
        if metric is not None:
            return metric.fn(self._metric_inputs(metric, point))
        return self.ratio(code, point)

    def period_end(self, point: Point) -> date | None:
        """The date prices are read at: the period end (the `as_of` date for the latest period)."""
        return self._ends.get(point)

    def price_close(self, point: Point) -> tuple[date, Decimal] | None:
        """The close used for `point`: the last on or before its end date."""
        end = self._ends.get(point)
        if end is None:
            return None
        at = bisect_right(self._prices, end, key=lambda row: row[0])
        return self._prices[at - 1] if at else None

    def _at_point(self, code: str, point: Point) -> Decimal | None:
        """The `at_point` metrics: `price` (last close on or before the period end) and
        `earnings_growth` (net income growth over a year earlier in percentage points, None unless
        both are positive)."""
        if code == "price":
            close = self.price_close(point)
            return None if close is None else close[1]
        now = self._line("net_income_common", point)
        before = self._line("net_income_common", year_earlier(point))
        if now is None or before is None or now <= 0 or before <= 0:
            return None
        return (now / before - 1) * 100

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
