from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from bedrock.models.note import Note


@dataclass(frozen=True)
class LinkCount:
    canonical_code: str | None
    metric_kind: str | None
    metric_code: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    count: int


def list_for(
    session: Session,
    company_id: int,
    code: str | None = None,
    period: tuple[int, str] | None = None,
    metric: tuple[str, str] | None = None,
) -> list[Note]:
    """The company's notes, newest `note_date` first, then highest id. The subject is `code` (a
    line) or `metric` (kind, code), never both. A subject alone matches its notes and those of
    any of its cells; with `period` it matches that cell's notes and the subject's own. `period`
    alone matches the period's notes and the cell notes of that period."""
    stmt = select(Note).where(Note.company_id == company_id)
    subject = (
        Note.canonical_code == code
        if code is not None
        else None
        if metric is None
        else and_(Note.metric_kind == metric[0], Note.metric_code == metric[1])
    )
    in_period = (
        None
        if period is None
        else and_(Note.fiscal_year == period[0], Note.fiscal_period == period[1])
    )
    if subject is not None and in_period is not None:
        stmt = stmt.where(subject, or_(Note.fiscal_year.is_(None), in_period))
    elif subject is not None:
        stmt = stmt.where(subject)
    elif in_period is not None:
        stmt = stmt.where(in_period)
    return list(session.execute(stmt.order_by(Note.note_date.desc(), Note.id.desc())).scalars())


def get(session: Session, company_id: int, note_id: int) -> Note | None:
    """The note, only when it belongs to the company."""
    stmt = select(Note).where(Note.company_id == company_id, Note.id == note_id)
    return session.execute(stmt).scalar_one_or_none()


def link_counts(session: Session, company_id: int) -> list[LinkCount]:
    """One entry per distinct link (line, metric, year, period) with its note count, ordered by
    those; notes with no link at all are left out."""
    key = (
        Note.canonical_code,
        Note.metric_kind,
        Note.metric_code,
        Note.fiscal_year,
        Note.fiscal_period,
    )
    stmt = (
        select(*key, func.count())
        .where(
            Note.company_id == company_id,
            or_(
                Note.canonical_code.is_not(None),
                Note.metric_kind.is_not(None),
                Note.fiscal_year.is_not(None),
            ),
        )
        .group_by(*key)
        .order_by(*key)
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
