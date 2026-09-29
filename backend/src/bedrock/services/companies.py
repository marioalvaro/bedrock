from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.models.company import Company


def list_companies(session: Session) -> list[Company]:
    stmt = select(Company).order_by(Company.ticker)
    return list(session.execute(stmt).scalars().all())
