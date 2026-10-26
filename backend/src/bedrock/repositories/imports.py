from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.custom_line import CustomLine
from bedrock.models.imported_fact import ImportedFact
from bedrock.models.statement_import import StatementImport
from bedrock.repositories.numeric import plain


@dataclass(frozen=True)
class NewFact:
    """One value to store: in units and in the reported convention."""

    line_code: str
    fiscal_year: int
    fiscal_period: str
    period_start: date | None  # None for an instant
    period_end: date
    value: Decimal


@dataclass(frozen=True)
class NewLine:
    """A custom line an import lists: new, or stored already (then its label and flag change)."""

    code: str
    label: str
    statement: str
    parent_code: str
    kind: str
    unit: str
    children_complete: bool


def add_import(
    session: Session,
    company_id: int,
    filename: str,
    fmt: str,
    scale: str,
    imported_at: datetime,
    note: str | None,
    facts: Sequence[NewFact],
    lines: Sequence[NewLine] = (),
) -> StatementImport:
    """Adds the import, its facts and the custom lines it lists, and flushes (no commit)."""
    row = StatementImport(
        company_id=company_id,
        filename=filename,
        format=fmt,
        scale=scale,
        imported_at=imported_at,
        cells=len(facts),
        note=note,
    )
    session.add(row)
    session.flush()
    session.add_all(
        ImportedFact(
            import_id=row.id,
            company_id=company_id,
            line_code=f.line_code,
            fiscal_year=f.fiscal_year,
            fiscal_period=f.fiscal_period,
            period_start=f.period_start,
            period_end=f.period_end,
            value=f.value,
        )
        for f in facts
    )
    _store_lines(session, company_id, lines)
    session.flush()
    return row


def _store_lines(session: Session, company_id: int, lines: Sequence[NewLine]) -> None:
    """New lines go after the siblings stored; a line stored already keeps its place and parent."""
    stored = {ln.code: ln for ln in list_lines(session, company_id)}
    for line in lines:
        known = stored.get(line.code)
        if known is not None:
            known.label = line.label
            known.children_complete = line.children_complete
            continue
        placed = [ln.display_order for ln in stored.values() if ln.parent_code == line.parent_code]
        stored[line.code] = row = CustomLine(
            company_id=company_id,
            code=line.code,
            label=line.label,
            statement=line.statement,
            parent_code=line.parent_code,
            kind=line.kind,
            unit=line.unit,
            children_complete=line.children_complete,
            display_order=max(placed, default=-1) + 1,
        )
        session.add(row)


def list_lines(session: Session, company_id: int) -> list[CustomLine]:
    """The company's custom lines, siblings in display order."""
    stmt = (
        select(CustomLine)
        .where(CustomLine.company_id == company_id)
        .order_by(CustomLine.display_order, CustomLine.id)
    )
    return list(session.execute(stmt).scalars())


def list_imports(session: Session, company_id: int) -> list[StatementImport]:
    """The company's imports, newest first."""
    stmt = (
        select(StatementImport)
        .where(StatementImport.company_id == company_id)
        .order_by(StatementImport.imported_at.desc(), StatementImport.id.desc())
    )
    return list(session.execute(stmt).scalars())


def get(session: Session, company_id: int, import_id: int) -> StatementImport | None:
    """The import, only when it belongs to the company."""
    stmt = select(StatementImport).where(
        StatementImport.company_id == company_id, StatementImport.id == import_id
    )
    return session.execute(stmt).scalar_one_or_none()


def list_facts(session: Session, company_id: int) -> list[ImportedFact]:
    """Every imported value of the company, every vintage, in one query: by line, period, then
    import (oldest first), with plain-decimal values (`repositories/numeric.py::plain`)."""
    stmt = (
        select(ImportedFact)
        .where(ImportedFact.company_id == company_id)
        .order_by(
            ImportedFact.line_code,
            ImportedFact.fiscal_year,
            ImportedFact.fiscal_period,
            ImportedFact.import_id,
        )
    )
    found = list(session.execute(stmt).scalars())
    for fact in found:
        # Not a change: the stored value is the same, only without Numeric's padding.
        set_committed_value(fact, "value", plain(fact.value))
    return found


def delete_import(session: Session, row: StatementImport) -> None:
    """Deletes the import and its facts, then the custom lines left with no value and no line
    under them (a line goes with the last import that has values for it), and flushes (no
    commit)."""
    company_id = row.company_id
    session.delete(row)
    session.flush()
    while True:
        valued = set(
            session.execute(
                select(ImportedFact.line_code)
                .where(ImportedFact.company_id == company_id)
                .group_by(ImportedFact.line_code)
            ).scalars()
        )
        lines = list_lines(session, company_id)
        parents = {ln.parent_code for ln in lines}
        gone = [ln for ln in lines if ln.code not in valued and ln.code not in parents]
        if not gone:
            return
        for line in gone:
            session.delete(line)
        session.flush()
