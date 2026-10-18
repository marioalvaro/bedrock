from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import PriceRow
from bedrock.models.price_daily import PriceDaily
from bedrock.repositories.numeric import plain


def last_date(session: Session, company_id: int) -> date | None:
    stmt = select(func.max(PriceDaily.date)).where(PriceDaily.company_id == company_id)
    return session.execute(stmt).scalar_one()


def latest_close(session: Session, company_id: int) -> tuple[date, Decimal] | None:
    stmt = (
        select(PriceDaily.date, PriceDaily.close)
        .where(PriceDaily.company_id == company_id)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    return None if row is None else (row.date, plain(row.close))


def closes(session: Session, company_id: int) -> list[tuple[date, Decimal]]:
    """Every stored `(date, close)` of the company, oldest first."""
    stmt = (
        select(PriceDaily.date, PriceDaily.close)
        .where(PriceDaily.company_id == company_id)
        .order_by(PriceDaily.date)
    )
    return [(row.date, plain(row.close)) for row in session.execute(stmt)]


def insert_new(session: Session, company_id: int, rows: Sequence[PriceRow]) -> int:
    """Store the rows whose date is not stored yet; returns how many were added."""
    stmt = select(PriceDaily.date).where(PriceDaily.company_id == company_id)
    known = set(session.execute(stmt).scalars())
    fresh = [
        {
            "company_id": company_id,
            "date": r.date,
            "close": r.close,
            "adj_close": r.adj_close,
            "volume": r.volume,
        }
        for r in rows
        if r.date not in known
    ]
    if fresh:
        session.execute(insert(PriceDaily), fresh)
    return len(fresh)
