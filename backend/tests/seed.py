"""Helpers that put a followed company into a test database."""

from sqlalchemy.orm import Session

from bedrock.ingest.protocol import EdgarLike
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company

from .fakes import FakeEdgar, FakePrices


def fake_sources() -> Sources:
    return Sources(edgar=FakeEdgar(), prices=FakePrices())


def follow(session: Session, edgar: EdgarLike, ticker: str) -> Company:
    """A followed company with no data yet (what `add_company` inserts before refreshing)."""
    profile = edgar.resolve(ticker)
    company = Company(
        ticker=profile.ticker,
        cik=profile.cik,
        name=profile.name,
        fiscal_year_end_month=profile.fiscal_year_end_month,
        currency="USD",
        sic=profile.sic,
        last_refreshed_at=None,
    )
    session.add(company)
    session.commit()
    return company
