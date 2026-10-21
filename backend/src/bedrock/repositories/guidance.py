from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.guidance import Guidance
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[Guidance]:
    """The company's entries by id, with plain-decimal ranges
    (`repositories/numeric.py::plain`)."""
    stmt = select(Guidance).where(Guidance.company_id == company_id).order_by(Guidance.id)
    return [_plain_range(g) for g in session.execute(stmt).scalars()]


def get(session: Session, company_id: int, guidance_id: int) -> Guidance | None:
    """The entry, only when it belongs to the company; plain-decimal range."""
    stmt = select(Guidance).where(Guidance.company_id == company_id, Guidance.id == guidance_id)
    found = session.execute(stmt).scalar_one_or_none()
    return None if found is None else _plain_range(found)


def add(session: Session, entry: Guidance) -> Guidance:
    """Adds and flushes (no commit)."""
    session.add(entry)
    session.flush()
    return entry


def delete(session: Session, entry: Guidance) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(entry)
    session.flush()


def _plain_range(entry: Guidance) -> Guidance:
    # Not a change: the stored values are the same, only without Numeric's padding.
    set_committed_value(entry, "low", plain(entry.low))
    set_committed_value(entry, "high", plain(entry.high))
    return entry
