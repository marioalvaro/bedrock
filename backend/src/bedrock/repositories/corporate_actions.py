from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.ingest.protocol import SplitRow
from bedrock.models.corporate_action import CorporateAction
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[CorporateAction]:
    """The company's corporate actions, oldest first, with plain-decimal ratios."""
    stmt = (
        select(CorporateAction)
        .where(CorporateAction.company_id == company_id)
        .order_by(CorporateAction.effective_date)
    )
    actions = list(session.execute(stmt).scalars())
    for action in actions:
        # Not a change: the stored value is the same, only without Numeric's padding.
        set_committed_value(action, "ratio", plain(action.ratio))
    return actions


def insert_new(
    session: Session, company_id: int, splits: Sequence[SplitRow], source: str = "yfinance"
) -> int:
    """Store the splits whose effective date is not stored yet; returns how many were added."""
    stmt = select(CorporateAction.effective_date).where(CorporateAction.company_id == company_id)
    known = set(session.execute(stmt).scalars())
    fresh = list({s.effective_date: s for s in splits if s.effective_date not in known}.values())
    session.add_all(
        CorporateAction(
            company_id=company_id,
            type="split" if s.ratio > 1 else "reverse_split",
            effective_date=s.effective_date,
            ratio=s.ratio,
            source=source,
        )
        for s in fresh
    )
    session.flush()  # the session does not autoflush, and the next call reads what is stored
    return len(fresh)
