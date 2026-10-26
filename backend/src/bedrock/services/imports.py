"""Manual statement import (FR-DATA-15): the template, a dry run, the confirmed import, its history.

An import only fills the cells the SEC data leaves empty (docs/erd/data.md "Precedence"). The
preview compares what the file says with the company's statements three ways: SEC data alone (a
value there always wins), the statements as they are (earlier imports), and the statements with
this file on top (what would change).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from bedrock.ingest.import_template import build_template
from bedrock.ingest.manual_import import (
    ImportFormat,
    ImportIssue,
    ImportParseError,
    ImportPlan,
    check_periods,
    parse_import,
)
from bedrock.mapping.config import CanonicalItemDef
from bedrock.models.company import Company
from bedrock.models.statement_import import StatementImport
from bedrock.repositories import imports as repo
from bedrock.services.errors import ImportNotFound, InvalidStatementImport
from bedrock.services.statements import load_inputs
from bedrock.statements.cell_types import EMPTY, CellKey
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.imports import (
    StoredValue,
    company_calendar,
    imported_frames,
    integrity_warnings,
)
from bedrock.statements.periods import annual_periods, fiscal_calendar, quarterly_periods

PERIOD_ORDER = ("FY", "Q1", "Q2", "Q3", "Q4")
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
class ImportPreview:
    format: ImportFormat
    scale: str
    fills: list[CellChange]
    ignored: list[IgnoredCell]
    unchanged: int  # typed values equal to what the cell already shows
    warnings: list[ImportIssue]


@dataclass(frozen=True)
class ImportResult:
    preview: ImportPreview
    import_id: int | None  # None when nothing was stored (the file fills no cell)


def import_template(
    session: Session, company: Company, fmt: ImportFormat, scale: str, prefill: bool
) -> bytes:
    """The template of the company's periods; `prefill` writes the values the statements show
    (reported basis). Raises ValueError for an unknown scale."""
    inputs = load_inputs(session, company)
    calendar = company_calendar(inputs.canonical, inputs.rules.imported)
    periods = sorted(
        annual_periods(calendar) + quarterly_periods(calendar),
        key=lambda p: (p.fiscal_year, PERIOD_ORDER.index(p.fiscal_period)),
    )
    values: dict[tuple[str, str], Decimal] = {}
    if prefill and not inputs.empty:
        solved = solve_cells(inputs.canonical, inputs.items, calendar, inputs.rules)
        values = {key: cell.value for key, cell in solved.cells.items() if cell.value is not None}
    return build_template(inputs.items, periods, fmt, scale, values)


def preview_import(
    session: Session, company: Company, content: bytes, filename: str, scale: str | None
) -> ImportPreview:
    """The dry run: what the file would fill, what it would leave alone and why. Writes nothing.
    Raises InvalidStatementImport with every error of the file."""
    return _evaluate(session, company, content, filename, scale, datetime.min)[0]


def confirm_import(
    session: Session,
    company: Company,
    content: bytes,
    filename: str,
    scale: str | None,
    now: datetime,
) -> ImportResult:
    """Stores the cells the file fills as one import. A file that fills nothing stores nothing."""
    preview, plan, fills = _evaluate(session, company, content, filename, scale, now)
    if not fills:
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
) -> tuple[ImportPreview, ImportPlan, list[StoredValue]]:
    inputs = load_inputs(session, company)
    items = {i.code: i for i in inputs.items}
    try:
        parsed = parse_import(content, filename, inputs.items, scale)
    except ImportParseError as error:
        raise InvalidStatementImport(error.errors) from error
    sec_calendar = fiscal_calendar(inputs.canonical)
    current_calendar = company_calendar(inputs.canonical, inputs.rules.imported)
    issues, plan = check_periods(parsed, sec_calendar, current_calendar)
    if issues:
        raise InvalidStatementImport(issues)

    typed = _stored(plan, items, now)
    sec = solve_cells(
        inputs.canonical,
        inputs.items,
        sec_calendar,
        replace(inputs.rules, imported=None, imported_vintages=None),
    )
    current = solve_cells(inputs.canonical, inputs.items, current_calendar, inputs.rules)
    frames = imported_frames([*inputs.imports, *typed], inputs.items)
    rules = replace(inputs.rules, imported=frames.newest, imported_vintages=frames.vintages)
    after_calendar = company_calendar(inputs.canonical, frames.newest)
    after = solve_cells(inputs.canonical, inputs.items, after_calendar, rules)

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
        elif now_cell.provenance == "imported" and now_cell.value == shown:
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
    preview = ImportPreview(plan.format, plan.scale, changes, ignored, unchanged, warnings)
    return preview, plan, fills


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
