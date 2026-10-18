from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.adjustment import Adjustment
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[Adjustment]:
    """The company's adjustments in insertion order, with plain-decimal amounts."""
    stmt = select(Adjustment).where(Adjustment.company_id == company_id).order_by(Adjustment.id)
    return [_plain_amount(a) for a in session.execute(stmt).scalars()]


def get(session: Session, company_id: int, adjustment_id: int) -> Adjustment | None:
    """The adjustment, only when it belongs to the company."""
    stmt = select(Adjustment).where(
        Adjustment.company_id == company_id, Adjustment.id == adjustment_id
    )
    found = session.execute(stmt).scalar_one_or_none()
    return None if found is None else _plain_amount(found)


def add(session: Session, adjustment: Adjustment) -> Adjustment:
    session.add(adjustment)
    session.flush()
    return _plain_amount(adjustment)


def delete(session: Session, adjustment: Adjustment) -> None:
    session.delete(adjustment)
    session.flush()


def _plain_amount(adjustment: Adjustment) -> Adjustment:
    # Not a change: the stored value is the same, only without Numeric's padding.
    set_committed_value(adjustment, "amount", plain(adjustment.amount))
    return adjustment
