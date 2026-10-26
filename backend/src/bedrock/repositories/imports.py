from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

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


def add_import(
    session: Session,
    company_id: int,
    filename: str,
    fmt: str,
    scale: str,
    imported_at: datetime,
    note: str | None,
    facts: Sequence[NewFact],
) -> StatementImport:
    """Adds the import and its facts and flushes (no commit)."""
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
    session.flush()
    return row


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
    """Deletes the import and its facts and flushes (no commit)."""
    session.delete(row)
    session.flush()
