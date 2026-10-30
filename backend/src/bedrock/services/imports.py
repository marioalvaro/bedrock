"""Manual statement import (FR-DATA-15): the template, a dry run, the confirmed import, its history.

An import only fills the cells the SEC data leaves empty (docs/erd/data.md "Precedence"). The
preview compares what the file says with the company's statements three ways: SEC data alone (a
value there always wins), the statements as they are (earlier imports), and the statements with
this file on top (what would change).
"""

import calendar as month_calendar
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from bedrock.ingest.import_template import build_template
from bedrock.ingest.manual_import import (
    ImportFormat,
    ImportIssue,
    ImportParseError,
    ImportPlan,
    PlanLine,
    check_periods,
    parse_import,
)
from bedrock.mapping.config import CanonicalItemDef
from bedrock.models.company import Company
from bedrock.models.custom_line import CustomLine
from bedrock.models.statement_import import StatementImport
from bedrock.repositories import imports as repo
from bedrock.services.errors import ImportNotFound, InvalidStatementImport
from bedrock.services.statements import load_inputs
from bedrock.statements.cell_types import EMPTY, CellKey
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.custom_lines import (
    BUILT_FROM_CHILDREN,
    LineSpec,
    complete_parents,
    custom_items,
    merge_lines,
)
from bedrock.statements.fiscal_grid import annual_then_quarterly, period_grid
from bedrock.statements.imports import (
    StoredValue,
    company_calendar,
    imported_frames,
    integrity_warnings,
)
from bedrock.statements.periods import (
    Calendar,
    Period,
    annual_periods,
    fiscal_calendar,
    fiscal_year_of,
    quarterly_periods,
)

NEW_IMPORT_ID = 10**9  # the id the dry run gives the file, so its cells can be told apart

IgnoredReason = Literal["sec", "derived"]


@dataclass(frozen=True)
class CellChange:
    """A cell the import fills. Values are displayed (sign applied), in units."""

    statement: str
    code: str
    label: str
    unit: str
    period_key: str
    value: Decimal
    previous: Decimal | None  # the value an earlier import gave the cell, if it changes


@dataclass(frozen=True)
class IgnoredCell:
    """A typed value that differs from what the cell already shows, and is not used: `sec` when
    the SEC data (or a rule over it) has the cell, `derived` when a formula produces another
    value."""

    statement: str
    code: str
    label: str
    unit: str
    period_key: str
    existing_value: Decimal
    imported_value: Decimal
    reason: IgnoredReason


@dataclass(frozen=True)
class LineChange:
    """A custom line the import creates."""

    statement: str
    code: str
    label: str
    parent: str
    parent_label: str


@dataclass(frozen=True)
class BuiltCell:
    """A parent cell that the sum of a complete custom breakdown fills (or changes)."""

    statement: str
    code: str
    label: str
    unit: str
    period_key: str
    value: Decimal  # displayed, in units


@dataclass(frozen=True)
class ImportPreview:
    format: ImportFormat
    scale: str
    fills: list[CellChange]
    ignored: list[IgnoredCell]
    unchanged: int  # typed values equal to what the cell already shows
    warnings: list[ImportIssue]
    lines: list[LineChange] = field(default_factory=list)  # custom lines created
    built: list[BuiltCell] = field(default_factory=list)  # parent cells built from their lines


@dataclass(frozen=True)
class ImportResult:
    preview: ImportPreview
    import_id: int | None  # None when nothing was stored (no cell filled, no line changed)


def import_template(
    session: Session,
    company: Company,
    fmt: ImportFormat,
    scale: str,
    prefill: bool,
    today: date | None = None,
) -> bytes:
    """The template: 20 fiscal years of columns (FY, Q1..Q4 each), the company's own periods
    included, and the fiscal year end its dates follow from. `prefill` writes the values the
    statements show (reported basis). `today` places a company with no data. Raises ValueError for
    an unknown scale."""
    inputs = load_inputs(session, company)
    calendar = company_calendar(inputs.canonical, inputs.rules.imported)
    fiscal_year_end, last_year = _template_frame(company, calendar, today or date.today())
    own = annual_periods(calendar) + quarterly_periods(calendar)
    by_key: dict[str, Period] = {p.key: p for p in period_grid(fiscal_year_end, last_year)}
    by_key.update({p.key: p for p in own})
    periods = annual_then_quarterly(by_key.values())
    values: dict[tuple[str, str], Decimal] = {}
    if prefill and not inputs.empty:
        solved = solve_cells(inputs.canonical, inputs.lines, calendar, inputs.rules)
        values = {key: cell.value for key, cell in solved.cells.items() if cell.value is not None}
    return build_template(inputs.items, periods, fmt, scale, values, fiscal_year_end)


def _template_frame(company: Company, calendar: Calendar, today: date) -> tuple[date, int]:
    """The fiscal year end to write and the last fiscal year of the grid. A company with a
    calendar ends at its latest year (the open one included) and takes the end of its latest
    completed year; one without data ends at the fiscal year that contains `today`."""
    if calendar.years:
        return _year_end_fallback(company, calendar), calendar.years[-1].fiscal_year
    month = company.fiscal_year_end_month
    candidate = date(today.year, month, month_calendar.monthrange(today.year, month)[1])
    if candidate >= today:
        year = candidate.year - 1
        candidate = date(year, month, month_calendar.monthrange(year, month)[1])
    return candidate, fiscal_year_of(candidate) + 1


def _month_end_reference(company: Company) -> date:
    """A fiscal year end on the last day of the company's fiscal-year month (any year works)."""
    month = company.fiscal_year_end_month
    return date(2001, month, month_calendar.monthrange(2001, month)[1])


def _year_end_fallback(company: Company, calendar: Calendar) -> date:
    """The fiscal year end for a file that has none: the latest completed year's, else the
    company's fiscal-year month."""
    completed = annual_periods(calendar)
    return completed[-1].end if completed else _month_end_reference(company)


def preview_import(
    session: Session, company: Company, content: bytes, filename: str, scale: str | None
) -> ImportPreview:
    """The dry run: what the file would fill, what it would leave alone and why. Writes nothing.
    Raises InvalidStatementImport with every error of the file. The file ranks as the newest
    import, as it will on Confirm."""
    return _evaluate(session, company, content, filename, scale, datetime.max)[0]


def confirm_import(
    session: Session,
    company: Company,
    content: bytes,
    filename: str,
    scale: str | None,
    now: datetime,
) -> ImportResult:
    """Stores the cells the file fills, and the custom lines it adds or changes, as one import. A
    file that does neither stores nothing."""
    preview, plan, fills, lines = _evaluate(session, company, content, filename, scale, now)
    if not fills and not lines:
        return ImportResult(preview, None)
    row = repo.add_import(
        session,
        company.id,
        filename,
        plan.format,
        plan.scale,
        _naive(now),
        None,
        [
            repo.NewFact(
                v.line_code, v.fiscal_year, v.fiscal_period, v.period_start, v.period_end, v.value
            )
            for v in fills
        ],
        lines,
    )
    session.commit()
    return ImportResult(preview, row.id)


def list_imports(session: Session, company: Company) -> list[StatementImport]:
    """The company's imports, newest first."""
    return repo.list_imports(session, company.id)


def delete_import(session: Session, company: Company, import_id: int) -> None:
    """Removes the import and its values; the cells it filled go back to what SEC says."""
    row = repo.get(session, company.id, import_id)
    if row is None:
        raise ImportNotFound(str(import_id))
    repo.delete_import(session, row)
    session.commit()


# -- the comparison ---------------------------------------------------------------------------


def _evaluate(
    session: Session,
    company: Company,
    content: bytes,
    filename: str,
    scale: str | None,
    now: datetime,
) -> tuple[ImportPreview, ImportPlan, list[StoredValue], list[repo.NewLine]]:
    inputs = load_inputs(session, company)
    sec_calendar = fiscal_calendar(inputs.canonical)
    current_calendar = company_calendar(inputs.canonical, inputs.rules.imported)
    try:
        parsed = parse_import(
            content,
            filename,
            inputs.items,
            scale,
            inputs.custom,
            _year_end_fallback(company, current_calendar),
        )
    except ImportParseError as error:
        raise InvalidStatementImport(error.errors) from error
    issues, plan = check_periods(parsed, sec_calendar, current_calendar)
    if issues:
        raise InvalidStatementImport(issues)

    # The company's lines once the file is on top: the stored ones (a listed line takes the file's
    # label and flag) and the new ones.
    stored_lines = {r.code: r for r in repo.list_lines(session, company.id)}
    specs = _specs_after(stored_lines.values(), plan)
    lines_after = merge_lines(inputs.items, custom_items(inputs.items, specs))
    items = {i.code: i for i in lines_after}

    typed = _stored(plan, items, now)
    sec = solve_cells(
        inputs.canonical,
        inputs.items,
        sec_calendar,
        replace(inputs.rules, imported=None, imported_vintages=None, complete_parents=frozenset()),
    )
    current = solve_cells(inputs.canonical, inputs.lines, current_calendar, inputs.rules)
    frames = imported_frames([*inputs.imports, *typed], lines_after)
    rules = replace(
        inputs.rules,
        imported=frames.newest,
        imported_vintages=frames.vintages,
        complete_parents=complete_parents(
            (s.code, s.parent_code, s.children_complete) for s in specs
        ),
    )
    after_calendar = company_calendar(inputs.canonical, frames.newest)
    after = solve_cells(inputs.canonical, lines_after, after_calendar, rules)

    fills: list[StoredValue] = []
    changes: list[CellChange] = []
    ignored: list[IgnoredCell] = []
    unchanged = 0
    warnings: list[ImportIssue] = list(parsed.warnings)
    for value in typed:
        item = items[value.line_code]
        key = _key(value)
        shown = value.value * item.sign
        base = sec.cells.get(key, EMPTY)
        now_cell = current.cells.get(key, EMPTY)
        then = after.cells.get(key, EMPTY)
        if base.value is not None:
            if base.value == shown:
                unchanged += 1
            else:
                ignored.append(_ignored(item, key, base.value, shown, "sec"))
        elif then.value is None:
            warnings.append(
                ImportIssue(
                    None,
                    None,
                    None,
                    f"{item.label} {key[1]}: no period to put the value in (a new year needs "
                    "an income or cash-flow column with dates); ignored",
                )
            )
        elif then.value != shown:
            ignored.append(_ignored(item, key, then.value, shown, "derived"))
        elif now_cell.value == shown:
            unchanged += 1
        else:
            fills.append(value)
            previous = now_cell.value if now_cell.provenance == "imported" else None
            changes.append(
                CellChange(
                    item.statement, item.code, item.label, item.unit, key[1], shown, previous
                )
            )

    warnings += _engine_warnings(after, current, items)
    touched = {(items[v.line_code].statement, v.line_code, _key(v)[1]) for v in fills}
    warnings += [
        ImportIssue(None, None, None, text)
        for text in integrity_warnings(
            after.cells,
            [k for s, _, k in touched if s == "BS"],
            [k for s, _, k in touched if s == "CF"],
        )
    ]
    lines = _lines_to_store(plan, stored_lines, {v.line_code for v in fills})
    preview = ImportPreview(
        plan.format,
        plan.scale,
        changes,
        ignored,
        unchanged,
        warnings,
        [
            LineChange(ln.statement, ln.code, ln.label, ln.parent_code, items[ln.parent_code].label)
            for ln in lines
            if ln.code not in stored_lines
        ],
        _built(after, current, items),
    )
    return preview, plan, fills, lines


def _specs_after(stored: Iterable[LineSpec], plan: ImportPlan) -> list[repo.NewLine]:
    """Every custom line once the plan is applied, in display order: the stored ones (a line the
    file lists again takes its label and flag) and the new ones after them."""
    listed = {ln.code: ln for ln in plan.lines}
    out: list[repo.NewLine] = []
    for line in stored:
        again = listed.pop(line.code, None)
        out.append(
            repo.NewLine(
                line.code,
                line.label if again is None else again.label,
                line.statement,
                line.parent_code,
                line.kind,
                line.unit,
                line.children_complete if again is None else again.children_complete,
            )
        )
    out += [_new_line(ln) for ln in listed.values()]
    return out


def _new_line(line: PlanLine) -> repo.NewLine:
    return repo.NewLine(
        line.code,
        line.label,
        line.statement,
        line.parent,
        line.kind,
        line.unit,
        line.children_complete,
    )


def _lines_to_store(
    plan: ImportPlan, stored: dict[str, CustomLine], filled: set[str]
) -> list[repo.NewLine]:
    """The file's lines the import stores: a new one that has a filled cell or has a new line
    with one under it, and a stored one whose label or flag the file changes."""
    by_code = {ln.code: ln for ln in plan.lines}
    needed: set[str] = set()
    for code in filled:
        while code in by_code and code not in needed:
            needed.add(code)
            code = by_code[code].parent
    out = []
    for line in plan.lines:
        known = stored.get(line.code)
        if known is None:
            if line.code in needed:
                out.append(_new_line(line))
        elif (known.label, known.children_complete) != (line.label, line.children_complete):
            out.append(_new_line(line))
    return out


def _built(
    after: SolvedCells, current: SolvedCells, items: dict[str, CanonicalItemDef]
) -> list[BuiltCell]:
    """The parent cells the sum of a complete breakdown fills or changes."""
    out = []
    for (code, period_key), cell in sorted(after.cells.items()):
        derivation = cell.derivation
        if derivation is None or derivation.formula != BUILT_FROM_CHILDREN or cell.value is None:
            continue
        if current.cells.get((code, period_key), EMPTY).value == cell.value:
            continue
        item = items[code]
        out.append(BuiltCell(item.statement, code, item.label, item.unit, period_key, cell.value))
    return out


def _stored(
    plan: ImportPlan, items: dict[str, CanonicalItemDef], now: datetime
) -> list[StoredValue]:
    """The plan's values as stored values of one new import. A balance-sheet value of Q4 that the
    year's value (the same date) already gives is dropped."""
    period = {p.key: p for p in plan.periods}
    years = {(v.code, v.fiscal_year) for v in plan.values if v.fiscal_period == "FY"}
    stored: list[StoredValue] = []
    for v in plan.values:
        item = items[v.code]
        instant = item.kind == "instant"
        if instant and v.fiscal_period == "Q4" and (v.code, v.fiscal_year) in years:
            continue
        p = period[v.period_key]
        stored.append(
            StoredValue(
                NEW_IMPORT_ID,
                "",
                _naive(now),
                v.code,
                v.fiscal_year,
                v.fiscal_period,
                None if instant else p.start,
                p.end,
                v.value,
            )
        )
    return stored


def _key(value: StoredValue) -> CellKey:
    key = f"FY{value.fiscal_year}"
    return (value.line_code, key if value.fiscal_period == "FY" else f"{key}{value.fiscal_period}")


def _ignored(
    item: CanonicalItemDef, key: CellKey, existing: Decimal, typed: Decimal, reason: IgnoredReason
) -> IgnoredCell:
    return IgnoredCell(
        item.statement,
        item.code,
        item.label,
        item.unit,
        key[1],
        existing,
        typed,
        reason,
    )


def _engine_warnings(
    after: SolvedCells, current: SolvedCells, items: dict[str, CanonicalItemDef]
) -> list[ImportIssue]:
    """The rule warnings the file adds (a Q4 that disagrees, operands of different sources)."""
    known = {(w.rule, w.code, w.period_key) for w in current.warnings}
    out = []
    for w in after.warnings:
        if (w.rule, w.code, w.period_key) in known:
            continue
        label = items[w.code].label if w.code in items else w.code
        out.append(ImportIssue(None, None, None, f"{label} {w.period_key}: {w.reason}"))
    return out


def _naive(moment: datetime) -> datetime:
    return moment.replace(tzinfo=None)
