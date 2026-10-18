from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.off_balance_item import OffBalanceItem
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[OffBalanceItem]:
    """The company's items, newest `as_of` first, then newest id first, with plain-decimal
    amounts (`repositories/numeric.py::plain`)."""
    stmt = (
        select(OffBalanceItem)
        .where(OffBalanceItem.company_id == company_id)
        .order_by(OffBalanceItem.as_of.desc(), OffBalanceItem.id.desc())
    )
    return [_plain_amount(i) for i in session.execute(stmt).scalars()]


def get(session: Session, company_id: int, item_id: int) -> OffBalanceItem | None:
    """The item, only when it belongs to the company; plain-decimal amount."""
    stmt = select(OffBalanceItem).where(
        OffBalanceItem.company_id == company_id, OffBalanceItem.id == item_id
    )
    found = session.execute(stmt).scalar_one_or_none()
    return None if found is None else _plain_amount(found)


def add(session: Session, item: OffBalanceItem) -> OffBalanceItem:
    """Adds and flushes (no commit)."""
    session.add(item)
    session.flush()
    return _plain_amount(item)


def delete(session: Session, item: OffBalanceItem) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(item)
    session.flush()


def _plain_amount(item: OffBalanceItem) -> OffBalanceItem:
    # Not a change: the stored value is the same, only without Numeric's padding.
    if item.amount is not None:
        set_committed_value(item, "amount", plain(item.amount))
    return item
