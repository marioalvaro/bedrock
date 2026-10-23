"""Capital allocation (FR-ANL-06; docs/erd/analysis.md "Capital allocation (M2)"). Pure.

Operands are read through `ratios/calculator.py::Operands`, like the ratios.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.ratios.calculator import Operands, Point, RatioFreq, RatioInputs, year_earlier
from bedrock.statements.build import RATIO_PLACES, growth
from bedrock.statements.periods import Period

CapitalUnit = Literal["USD", "x", "pct"]


@dataclass(frozen=True)
class CapitalRow:
    code: str
    label: str
    unit: CapitalUnit
    values: list[Decimal | None]  # aligned with CapitalAllocationTable.periods
    pct_of_cfo: list[Decimal | None] | None  # None for rows without the ERD's "yes" mark
    pct_of_fcf: list[Decimal | None] | None


@dataclass(frozen=True)
class CapitalAllocationTable:
    freq: RatioFreq
    periods: list[Period]
    rows: list[CapitalRow]


def capital_allocation(inputs: RatioInputs, freq: RatioFreq) -> CapitalAllocationTable:
    """The ERD's ten rows, in its order, over the periods of `inputs.income`.

    Postconditions: USD rows are the statement values unchanged (displayed sign convention,
    outflows negative); `capex_to_da` (x), `net_share_change` (pct, `statements/build.py::growth`
    of shares_outstanding a year earlier) and every `pct_of_*` entry are quantized to RATIO_PLACES;
    `pct_of_cfo` = -value / cfo and `pct_of_fcf` = -value / free_cash_flow, None when the value or
    base is None or the base <= 0; `shareholder_returns` is None unless both buybacks and
    dividends_paid have a value. A period in which no row has a value is left out. Raises
    ValueError when `freq` is `ttm` and `quarterly_income` is None."""
    if freq == "ttm" and inputs.quarterly_income is None:
        raise ValueError("TTM capital allocation needs the quarterly income statement")
    operands = Operands(inputs, freq)
    periods = inputs.income.periods
    points: list[Point] = [(p.fiscal_year, p.fiscal_period) for p in periods]
    grid = [[_value(operands, spec, point) for point in points] for spec in _ROWS]
    cfo, fcf = grid[0], grid[1]
    kept = [i for i in range(len(periods)) if any(values[i] is not None for values in grid)]

    def pick(values: list[Decimal | None]) -> list[Decimal | None]:
        return [values[i] for i in kept]

    return CapitalAllocationTable(
        freq=freq,
        periods=[periods[i] for i in kept],
        rows=[
            CapitalRow(
                code=spec.code,
                label=spec.label,
                unit=spec.unit,
                values=pick(values),
                pct_of_cfo=pick(_shares(values, cfo)) if spec.pct else None,
                pct_of_fcf=pick(_shares(values, fcf)) if spec.pct else None,
            )
            for spec, values in zip(_ROWS, grid, strict=True)
        ],
    )


@dataclass(frozen=True)
class _RowSpec:
    code: str
    label: str
    unit: CapitalUnit
    operand: str  # a canonical code or formula read through `Operands`; "" for a derived row
    pct: bool  # the ERD's "% of CFO / FCF" mark


# cfo and free_cash_flow come first: the % columns divide by them.
_ROWS = (
    _RowSpec("cfo", "Cash from operations", "USD", "cfo", False),
    _RowSpec("free_cash_flow", "Free cash flow", "USD", "free_cash_flow", False),
    _RowSpec("capex", "Capital expenditures", "USD", "capex", True),
    _RowSpec("d_and_a", "Depreciation & amortization", "USD", "d_and_a", False),
    _RowSpec("capex_to_da", "Capex / D&A", "x", "", False),
    _RowSpec("acquisitions", "Acquisitions", "USD", "acquisitions", True),
    _RowSpec("buybacks", "Buybacks", "USD", "buybacks", True),
    _RowSpec("dividends_paid", "Dividends", "USD", "dividends_paid", True),
    _RowSpec(
        "shareholder_returns", "Buybacks + dividends", "USD", "buybacks + dividends_paid", True
    ),
    _RowSpec("net_share_change", "Net share-count change", "pct", "", False),
)


# code -> label of every capital metric (what a note links to).
CAPITAL_METRICS: dict[str, str] = {spec.code: spec.label for spec in _ROWS}


def _value(operands: Operands, spec: _RowSpec, point: Point) -> Decimal | None:
    if spec.code == "capex_to_da":
        capex = operands.operand("capex", point)
        d_and_a = operands.operand("d_and_a", point)
        if capex is None or d_and_a is None or d_and_a <= 0:
            return None
        return (-capex / d_and_a).quantize(RATIO_PLACES)
    if spec.code == "net_share_change":
        return growth(
            operands.operand("shares_outstanding", point),
            operands.operand("shares_outstanding", year_earlier(point)),
        )
    return operands.operand(spec.operand, point)


def _shares(values: list[Decimal | None], bases: list[Decimal | None]) -> list[Decimal | None]:
    """-value / base per period; None when either is None or the base <= 0."""
    return [
        None
        if value is None or base is None or base <= 0
        else (-value / base).quantize(RATIO_PLACES)
        for value, base in zip(values, bases, strict=True)
    ]
