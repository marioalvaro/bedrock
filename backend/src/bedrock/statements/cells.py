"""Discrete-period cells (fiscal years and quarters) with provenance. Pure.

A cell is the value of one canonical item in one period, plus what produced it: a source fact
(`reported`) or a derivation (`derived`). Statement tables and cell explanations read the same
cells, so what the grid shows and what the cell details say cannot drift apart.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef, formula_order, parse_formula
from bedrock.mapping.vintage import BALANCE_DATE_TOLERANCE
from bedrock.statements.periods import (
    START_TOLERANCE,
    Calendar,
    FiscalYear,
    Period,
    annual_periods,
    quarterly_periods,
)

Provenance = Literal["reported", "derived"]


@dataclass(frozen=True)
class FactRef:
    taxonomy: str
    concept: str
    unit: str
    period_start: date | None
    period_end: date
    accession_no: str
    form: str
    filed_at: date


@dataclass(frozen=True)
class DerivationInput:
    code: str
    fiscal_period: str  # FY, Q1..Q4, or "YTD Q2" for a year-to-date figure
    value: Decimal


@dataclass(frozen=True)
class Derivation:
    formula: str
    inputs: tuple[DerivationInput, ...]


@dataclass(frozen=True)
class Cell:
    value: Decimal | None
    provenance: Provenance | None
    source: FactRef | None = None
    derivation: Derivation | None = None


EMPTY = Cell(None, None)

CellKey = tuple[str, str]  # (code, period key)


@dataclass(frozen=True)
class _Fact:
    start: date | None
    end: date
    value: Decimal
    ref: FactRef
    split_factor: Decimal = Decimal(1)
    split_dates: tuple[date, ...] = ()
    reported_value: Decimal | None = None  # before the split factor; None = same as value


class _Index:
    """The canonical frame, looked up by (code, period end)."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._by_end: dict[tuple[str, date], list[_Fact]] = defaultdict(list)
        for r in frame.to_dict("records"):  # plain dicts: pandas-stubs types itertuples loosely
            start: date | None = None if pd.isna(r["period_start"]) else r["period_start"]
            ref = FactRef(
                r["taxonomy"],
                r["concept"],
                r["unit"],
                start,
                r["period_end"],
                r["accession_no"],
                r["form"],
                r["filed_at"],
            )
            self._by_end[(r["code"], r["period_end"])].append(
                _Fact(
                    start,
                    r["period_end"],
                    r["value"],
                    ref,
                    r.get("split_factor", Decimal(1)),
                    r.get("split_dates", ()),
                    r.get("reported_value"),
                )
            )

    def instant(self, code: str, end: date) -> _Fact | None:
        """The instant at `end`, else the nearest one within a week of it (a balance sheet dated
        a day off the fiscal period end). Exact dates always win."""
        exact = next((f for f in self._by_end.get((code, end), []) if f.start is None), None)
        if exact is not None:
            return exact
        for gap in range(1, BALANCE_DATE_TOLERANCE.days + 1):  # nearest first, earlier on a tie
            for when in (end - timedelta(days=gap), end + timedelta(days=gap)):
                found = next(
                    (f for f in self._by_end.get((code, when), []) if f.start is None), None
                )
                if found is not None:
                    return found
        return None

    def duration(self, code: str, start: date, end: date) -> _Fact | None:
        """The duration fact ending at `end` whose start is within a week of `start`."""
        near = [
            f
            for f in self._by_end.get((code, end), [])
            if f.start is not None and abs(f.start - start) <= START_TOLERANCE
        ]
        return min(near, key=lambda f: abs((f.start or start) - start), default=None)


def compute_cells(
    frame: pd.DataFrame, items: Sequence[CanonicalItemDef], calendar: Calendar
) -> dict[CellKey, Cell]:
    index = _Index(frame)
    years = {y.fiscal_year: y for y in calendar.years}
    cells: dict[CellKey, Cell] = {}
    periods = annual_periods(calendar) + quarterly_periods(calendar)

    for item in items:
        if item.residual:
            continue
        for period in periods:
            cells[(item.code, period.key)] = _mapped_cell(
                item, period, years[period.fiscal_year], index, cells
            )

    for item in formula_order(items):
        siblings = frozenset(i.code for i in items if item.residual and i.parent == item.parent)
        for period in periods:
            current = cells.get((item.code, period.key), EMPTY)
            if item.residual or current.value is None:
                cells[(item.code, period.key)] = _formula_cell(item, period, cells, siblings)
    return cells


def _mapped_cell(
    item: CanonicalItemDef,
    period: Period,
    year: FiscalYear,
    index: _Index,
    cells: dict[CellKey, Cell],
) -> Cell:
    code = item.code
    if item.kind == "instant":
        if period.fiscal_period == "Q4":  # the fiscal year-end balance
            return cells.get((code, f"FY{period.fiscal_year}"), EMPTY)
        return _reported(index.instant(code, period.end), code, period)
    if period.fiscal_period == "Q4":
        return EMPTY if item.kind == "average" else _q4(code, year, cells, index)
    reported = _reported(index.duration(code, period.start, period.end), code, period)
    if reported.value is not None or item.kind == "average" or period.fiscal_period == "FY":
        return reported
    return _from_year_to_date(code, period, year, index)


def _reported(fact: _Fact | None, code: str, period: Period) -> Cell:
    if fact is None:
        return EMPTY
    if fact.split_factor == 1:
        return Cell(fact.value, "reported", source=fact.ref)
    reported = fact.value if fact.reported_value is None else fact.reported_value
    return Cell(
        fact.value,
        "derived",
        source=fact.ref,
        derivation=Derivation(
            _split_formula(fact), (DerivationInput(code, period.fiscal_period, reported),)
        ),
    )


def _split_formula(fact: _Fact) -> str:
    op = "×" if fact.ref.unit == "shares" else "÷"
    noun = "split" if len(fact.split_dates) == 1 else "splits"
    dates = ", ".join(d.isoformat() for d in fact.split_dates)
    return f"as reported {op} {format(fact.split_factor.normalize(), 'f')} ({noun} {dates})"


def _quarter_number(period: Period) -> int:
    return int(period.fiscal_period[1])


def _from_year_to_date(code: str, period: Period, year: FiscalYear, index: _Index) -> Cell:
    n = _quarter_number(period)
    if n == 1:  # Q1 is its own year-to-date figure: either reported or missing
        return EMPTY
    this = index.duration(code, year.start, period.end)
    previous = index.duration(code, year.start, year.quarter_ends[n - 2])
    if this is None or previous is None:
        return EMPTY
    return Cell(
        this.value - previous.value,
        "derived",
        derivation=Derivation(
            f"YTD Q{n} - YTD Q{n - 1}",
            (
                DerivationInput(code, f"YTD Q{n}", this.value),
                DerivationInput(code, f"YTD Q{n - 1}", previous.value),
            ),
        ),
    )


def _q4(code: str, year: FiscalYear, cells: dict[CellKey, Cell], index: _Index) -> Cell:
    """FY less the three quarters as displayed, so the four quarters always add up to the year.
    The year-to-date Q3 fact can disagree with the 3-month facts of Q1..Q3 (restated later, or
    reported in another filing); Q4 absorbs that. When a quarter is unknown, FY - YTD Q3."""
    fiscal = cells.get((code, f"FY{year.fiscal_year}"), EMPTY)
    if fiscal.value is None:
        return EMPTY
    ytd_q3 = index.duration(code, year.start, year.quarter_ends[2])
    quarters = [cells.get((code, f"FY{year.fiscal_year}Q{n}"), EMPTY) for n in (1, 2, 3)]
    values = [q.value for q in quarters if q.value is not None]
    if len(values) < 3:
        if ytd_q3 is None:
            return EMPTY
        return _fy_less_ytd(code, fiscal.value, ytd_q3.value)
    total = sum(values, Decimal(0))
    if ytd_q3 is not None and ytd_q3.value == total:  # the usual case: say it the short way
        return _fy_less_ytd(code, fiscal.value, ytd_q3.value)
    return Cell(
        fiscal.value - total,
        "derived",
        derivation=Derivation(
            "FY - Q1 - Q2 - Q3",
            (
                DerivationInput(code, "FY", fiscal.value),
                *(
                    DerivationInput(code, f"Q{n}", v)
                    for n, v in zip((1, 2, 3), values, strict=True)
                ),
            ),
        ),
    )


def _fy_less_ytd(code: str, fiscal: Decimal, ytd_q3: Decimal) -> Cell:
    return Cell(
        fiscal - ytd_q3,
        "derived",
        derivation=Derivation(
            "FY - YTD Q3",
            (DerivationInput(code, "FY", fiscal), DerivationInput(code, "YTD Q3", ytd_q3)),
        ),
    )


def _formula_cell(
    item: CanonicalItemDef,
    period: Period,
    cells: dict[CellKey, Cell],
    siblings: frozenset[str] = frozenset(),
) -> Cell:
    """A residual treats a missing component of its own breakdown (`siblings`, the lines that
    share its parent) as 0; any other operand (the subtotal it completes, or a line outside the
    breakdown such as operating income) is required, or the residual is a number under the wrong
    label."""
    assert item.derive is not None
    terms = parse_formula(item.derive)
    operands = [(sign, code, cells.get((code, period.key), EMPTY).value) for sign, code in terms]
    if item.residual:
        if any(value is None and code not in siblings for _, code, value in operands):
            return EMPTY
    elif any(value is None for _, _, value in operands):
        return EMPTY
    total = sum((sign * value for sign, _, value in operands if value is not None), Decimal(0))
    inputs = tuple(
        DerivationInput(code, period.fiscal_period, value)
        for _, code, value in operands
        if value is not None
    )
    return Cell(total, "derived", derivation=Derivation(item.derive, inputs))
