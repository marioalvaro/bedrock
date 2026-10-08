from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.models.company import Company


def get_by_ticker(session: Session, ticker: str) -> Company | None:
    return session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()


def list_all(session: Session) -> list[Company]:
    return list(session.execute(select(Company).order_by(Company.ticker)).scalars().all())


def get_by_cik(session: Session, cik: str) -> Company | None:
    return session.execute(select(Company).where(Company.cik == cik)).scalar_one_or_none()
