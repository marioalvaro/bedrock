"""Thesis checkpoints of a company (docs/erd/workspace.md "Thesis checkpoints")."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.thesis_checkpoint import ThesisCheckpoint
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[ThesisCheckpoint]:
    """The company's checkpoints in id order, with a plain-decimal margin."""
    stmt = (
        select(ThesisCheckpoint)
        .where(ThesisCheckpoint.company_id == company_id)
        .order_by(ThesisCheckpoint.id)
    )
    return [_plain(c) for c in session.execute(stmt).scalars()]


def get(session: Session, company_id: int, checkpoint_id: int) -> ThesisCheckpoint | None:
    """The checkpoint, or None when there is none with this id on this company."""
    found = session.get(ThesisCheckpoint, checkpoint_id)
    return None if found is None or found.company_id != company_id else _plain(found)


def add(session: Session, checkpoint: ThesisCheckpoint) -> ThesisCheckpoint:
    """Adds and flushes (no commit)."""
    session.add(checkpoint)
    session.flush()
    return _plain(checkpoint)


def delete(session: Session, checkpoint: ThesisCheckpoint) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(checkpoint)
    session.flush()


def _plain(checkpoint: ThesisCheckpoint) -> ThesisCheckpoint:
    # Not a change: the stored value is the same, only without Numeric's padding.
    if checkpoint.margin is not None:
        set_committed_value(checkpoint, "margin", plain(checkpoint.margin))
    return checkpoint
