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

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef, formula_order, parse_formula
from bedrock.mapping.vintage import BALANCE_DATE_TOLERANCE
from bedrock.statements.averages import q4_average_cells
from bedrock.statements.cell_types import (
    EMPTY,
    Cell,
    CellKey,
    Derivation,
    DerivationInput,
    FactRef,
    RuleWarning,
)
from bedrock.statements.periods import (
    START_TOLERANCE,
    Calendar,
    FiscalYear,
    Period,
    annual_periods,
    quarterly_periods,
)
from bedrock.statements.rules import (
    BALANCE_FLOOR,
    BALANCE_RELATIVE,
    NO_RULES,
    Rules,
    WarningLog,
    infer_nci_zeros,
    solve_identities,
)

COVER_SHARES = "shares_outstanding"  # the line the cover-page count fills (R7)


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


@dataclass(frozen=True)
class SolvedCells:
    cells: dict[CellKey, Cell]
    warnings: tuple[RuleWarning, ...]  # rules whose result a guard refused (docs/erd/data.md R1)


def compute_cells(
    frame: pd.DataFrame,
    items: Sequence[CanonicalItemDef],
    calendar: Calendar,
    rules: Rules = NO_RULES,
) -> dict[CellKey, Cell]:
    return solve_cells(frame, items, calendar, rules).cells


def solve_cells(
    frame: pd.DataFrame,
    items: Sequence[CanonicalItemDef],
    calendar: Calendar,
    rules: Rules = NO_RULES,
) -> SolvedCells:
    """Every item in every fiscal year and quarter, in the pass order of docs/erd/data.md "Rule
    engine": mapped cells; then derive formulas, identities and the NCI rule filling empty cells
    until nothing changes, each sweep followed by Q4 (FY less the quarters, or the year-end
    balance); then residuals and the formulas that wait for them. A non-empty cell is never
    replaced."""
    index = _Index(frame)
    imported = None if rules.imported is None or rules.imported.empty else _Index(rules.imported)
    years = {y.fiscal_year: y for y in calendar.years}
    by_code = {i.code: i for i in items}
    cells: dict[CellKey, Cell] = {}
    periods = annual_periods(calendar) + quarterly_periods(calendar)
    log = WarningLog()

    for item in items:
        if item.residual:
            continue
        for period in periods:
            cells[(item.code, period.key)] = _mapped_cell(
                item, period, years[period.fiscal_year], index, cells, imported, log
            )

    solved_nonzero: set[CellKey] = set()
    cover = None if rules.cover_shares is None else _cover_index(rules.cover_shares)
    early = _formulas_before_residuals(items)
    while True:
        while True:
            filled = _fill_formulas(early, periods, cells)
            for key, cell in solve_identities(
                rules.identities, by_code, cells, periods, solved_nonzero, log
            ):
                filled += _fill(cells, key, cell)
            if rules.nci_filings is not None:
                for key, cell in infer_nci_zeros(cells, by_code, periods, rules.nci_filings):
                    filled += _fill(cells, key, cell)
            filled += _fill_cover_shares(periods, cells, cover)
            filled += _close_q4(items, periods, years, cells, index)
            if not filled:
                break
        # An imported value of a line with a formula counts only once the rules cannot fill it.
        if not _fill_imported_formula_lines(items, periods, cells, imported):
            break

    for key, cell in q4_average_cells(cells, by_code, periods, log):
        _fill(cells, key, cell)

    for item in formula_order(items):
        siblings = frozenset(i.code for i in items if item.residual and i.parent == item.parent)
        for period in periods:
            current = cells.get((item.code, period.key), EMPTY)
            if item.residual or current.value is None:
                cells[(item.code, period.key)] = _formula_cell(item, period, cells, siblings)
    return SolvedCells(cells, log.all())


def _fill(cells: dict[CellKey, Cell], key: CellKey, cell: Cell) -> int:
    """Store `cell` where the cell is empty (the rules never replace a value); 1 if it was."""
    if cell.value is None or cells.get(key, EMPTY).value is not None:
        return 0
    cells[key] = cell
    return 1


def _cover_index(frame: pd.DataFrame) -> _Index:
    """The cover-page counts, the latest filed first so that it wins where a period has several."""
    ordered = frame.sort_values(["filed_at", "accession_no"], ascending=False, kind="stable")
    return _Index(ordered)


def _fill_cover_shares(
    periods: Sequence[Period], cells: dict[CellKey, Cell], cover: _Index | None
) -> int:
    """R7: an empty shares-outstanding instant (FY and Q1-Q3; Q4 follows FY) takes the cover-page
    count of the filing that reports the period. Run after the identities, which are exact."""
    if cover is None:
        return 0
    filled = 0
    for period in periods:
        key = (COVER_SHARES, period.key)
        if period.fiscal_period == "Q4" or key not in cells:
            continue
        fact = cover.instant(COVER_SHARES, period.end)
        if fact is not None:
            filled += _fill(cells, key, _cover_cell(fact, period))
    return filled


def _cover_cell(fact: _Fact, period: Period) -> Cell:
    formula = f"cover-page shares outstanding of {fact.ref.form} {fact.ref.accession_no}"
    inputs: tuple[DerivationInput, ...] = ()
    if fact.split_factor != 1:
        reported = fact.value if fact.reported_value is None else fact.reported_value
        formula += f"; {_split_formula(fact)}"
        inputs = (DerivationInput(COVER_SHARES, period.fiscal_period, reported),)
    return Cell(fact.value, "approximated", source=fact.ref, derivation=Derivation(formula, inputs))


def _formulas_before_residuals(items: Sequence[CanonicalItemDef]) -> list[CanonicalItemDef]:
    """The non-residual formulas that do not depend on a residual, operands first. The rest keep
    their place after the residuals, which are computed once the rules filled their siblings."""
    by_code = {i.code: i for i in items}

    def waits(item: CanonicalItemDef) -> bool:
        if item.derive is None:
            return False
        return any(
            by_code[code].residual or waits(by_code[code]) for _, code in parse_formula(item.derive)
        )

    return [i for i in formula_order(items) if not i.residual and not waits(i)]


def _fill_formulas(
    formulas: Sequence[CanonicalItemDef], periods: Sequence[Period], cells: dict[CellKey, Cell]
) -> int:
    filled = 0
    for item in formulas:
        for period in periods:
            if cells.get((item.code, period.key), EMPTY).value is None:
                filled += _fill(cells, (item.code, period.key), _formula_cell(item, period, cells))
    return filled


def _close_q4(
    items: Sequence[CanonicalItemDef],
    periods: Sequence[Period],
    years: dict[int, FiscalYear],
    cells: dict[CellKey, Cell],
    index: _Index,
) -> int:
    """Q4 of what a rule filled in FY or Q1-Q3: FY less the three quarters for a flow, the year-end
    balance for an instant. Q4 of a flow whose year and quarters are all inferred zeros is an
    inferred zero too. Average items have no Q4."""
    filled = 0
    for item in items:
        if item.residual or item.kind == "average":
            continue
        for period in periods:
            key = (item.code, period.key)
            if period.fiscal_period != "Q4" or cells.get(key, EMPTY).value is not None:
                continue
            year = f"FY{period.fiscal_year}"
            if item.kind == "instant":
                filled += _fill(cells, key, cells.get((item.code, year), EMPTY))
                continue
            q4 = _q4(item.code, years[period.fiscal_year], cells, index)
            if q4.value == 0 and all(
                cells.get((item.code, f"{year}{suffix}"), EMPTY).provenance == "zero_inferred"
                for suffix in ("", "Q1", "Q2", "Q3")
            ):
                q4 = Cell(q4.value, "zero_inferred", derivation=q4.derivation)
            filled += _fill(cells, key, q4)
    return filled


def _mapped_cell(
    item: CanonicalItemDef,
    period: Period,
    year: FiscalYear,
    index: _Index,
    cells: dict[CellKey, Cell],
    imported: _Index | None,
    log: WarningLog,
) -> Cell:
    """The SEC value of the cell, else (R-import, docs/erd/data.md "Precedence") the imported one.
    A line with a formula takes its imported value later, only if the formula cannot run."""
    code = item.code
    typed = None if _has_formula(item) else imported
    if item.kind == "instant":
        if period.fiscal_period == "Q4":  # the fiscal year-end balance
            return cells.get((code, f"FY{period.fiscal_year}"), EMPTY)
        cell = _reported(index.instant(code, period.end), code, period)
        if cell.value is None and typed is not None:
            cell = _imported(typed.instant(code, period.end))
        return cell
    if period.fiscal_period == "Q4":
        if item.kind == "average":
            return (
                EMPTY
                if typed is None
                else _imported(typed.duration(code, period.start, period.end))
            )
        return _imported_q4(code, period, year, index, cells, typed, log)
    cell = _reported(index.duration(code, period.start, period.end), code, period)
    if cell.value is None and item.kind != "average" and period.fiscal_period != "FY":
        cell = _from_year_to_date(code, period, year, index)
    if cell.value is None and typed is not None:
        cell = _imported(typed.duration(code, period.start, period.end))
        if cell.value is None and period.fiscal_period == "FY" and item.kind == "flow":
            cell = _year_from_quarters(code, year, typed)
    return cell


def _has_formula(item: CanonicalItemDef) -> bool:
    return item.derive is not None and bool(item.concepts) and not item.residual


def _imported(fact: _Fact | None) -> Cell:
    return EMPTY if fact is None else Cell(fact.value, "imported", source=fact.ref)


def _quarter_spans(year: FiscalYear) -> list[tuple[date, date]]:
    """Start and end of Q1..Q4 of a year whose quarters are known."""
    if year.end is None or len(year.quarter_ends) != 3:
        return []
    ends = [*year.quarter_ends, year.end]
    starts = [year.start, *(end + timedelta(days=1) for end in year.quarter_ends)]
    return list(zip(starts, ends, strict=True))


def _year_from_quarters(code: str, year: FiscalYear, imported: _Index) -> Cell:
    """FY = Q1 + Q2 + Q3 + Q4 of imported quarters, all four required."""
    facts = [imported.duration(code, start, end) for start, end in _quarter_spans(year)]
    if len(facts) != 4 or any(f is None for f in facts):
        return EMPTY
    values = [f.value for f in facts if f is not None]
    return Cell(
        sum(values, Decimal(0)),
        "derived",
        derivation=Derivation(
            "Q1 + Q2 + Q3 + Q4",
            tuple(DerivationInput(code, f"Q{n}", v) for n, v in enumerate(values, start=1)),
        ),
    )


def _imported_q4(
    code: str,
    period: Period,
    year: FiscalYear,
    index: _Index,
    cells: dict[CellKey, Cell],
    imported: _Index | None,
    log: WarningLog,
) -> Cell:
    """Q4 of a flow: FY less the quarters as always; an imported Q4 fills it only when that is
    empty, and one that disagrees with the remainder is ignored with a warning."""
    remainder = _q4(code, year, cells, index)
    fact = None if imported is None else imported.duration(code, period.start, period.end)
    if fact is None:
        return remainder
    if remainder.value is None:
        return _imported(fact)
    unit = fact.ref.unit
    tolerance = (
        Decimal("0.01")
        if unit == "USD/shares"
        else max(BALANCE_FLOOR, BALANCE_RELATIVE * abs(remainder.value))
    )
    if abs(fact.value - remainder.value) > tolerance:
        log.add(
            RuleWarning(
                "import_q4",
                code,
                period.key,
                fact.value,
                f"imported Q4 ({fact.value}) differs from FY - Q1 - Q2 - Q3 "
                f"({remainder.value}); ignored",
            )
        )
    return remainder


def _fill_imported_formula_lines(
    items: Sequence[CanonicalItemDef],
    periods: Sequence[Period],
    cells: dict[CellKey, Cell],
    imported: _Index | None,
) -> int:
    """The imported value of a line with a formula (FY, Q1-Q3 and balance dates; Q4 follows), once
    the rules have run and left the cell empty."""
    if imported is None:
        return 0
    filled = 0
    for item in items:
        if not _has_formula(item):
            continue
        for period in periods:
            if period.fiscal_period == "Q4":
                continue
            fact = (
                imported.instant(item.code, period.end)
                if item.kind == "instant"
                else imported.duration(item.code, period.start, period.end)
            )
            filled += _fill(cells, (item.code, period.key), _imported(fact))
    return filled


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
