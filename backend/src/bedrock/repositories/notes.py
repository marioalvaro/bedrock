from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from bedrock.models.note import Note


@dataclass(frozen=True)
class LinkCount:
    canonical_code: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    count: int


def list_for(
    session: Session,
    company_id: int,
    code: str | None = None,
    period: tuple[int, str] | None = None,
) -> list[Note]:
    """The company's notes, newest `note_date` first, then highest id. `code` alone matches the
    line's notes and those of any of its cells; with `period` it matches that cell's notes and the
    line's own. `period` alone matches the period's notes and the cell notes of that period."""
    stmt = select(Note).where(Note.company_id == company_id)
    in_period = (
        None
        if period is None
        else and_(Note.fiscal_year == period[0], Note.fiscal_period == period[1])
    )
    if code is not None and in_period is not None:
        stmt = stmt.where(Note.canonical_code == code, or_(Note.fiscal_year.is_(None), in_period))
    elif code is not None:
        stmt = stmt.where(Note.canonical_code == code)
    elif in_period is not None:
        stmt = stmt.where(in_period)
    return list(session.execute(stmt.order_by(Note.note_date.desc(), Note.id.desc())).scalars())


def get(session: Session, company_id: int, note_id: int) -> Note | None:
    """The note, only when it belongs to the company."""
    stmt = select(Note).where(Note.company_id == company_id, Note.id == note_id)
    return session.execute(stmt).scalar_one_or_none()


def link_counts(session: Session, company_id: int) -> list[LinkCount]:
    """One entry per distinct link (code, year, period) with its note count, ordered by code,
    year, period; notes with no link at all are left out."""
    stmt = (
        select(Note.canonical_code, Note.fiscal_year, Note.fiscal_period, func.count())
        .where(
            Note.company_id == company_id,
            or_(Note.canonical_code.is_not(None), Note.fiscal_year.is_not(None)),
        )
        .group_by(Note.canonical_code, Note.fiscal_year, Note.fiscal_period)
        .order_by(Note.canonical_code, Note.fiscal_year, Note.fiscal_period)
    )
    return [LinkCount(*row) for row in session.execute(stmt)]


def add(session: Session, note: Note) -> Note:
    """Adds and flushes (no commit)."""
    session.add(note)
    session.flush()
    return note


def delete(session: Session, note: Note) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(note)
    session.flush()
