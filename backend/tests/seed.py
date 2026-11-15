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


def read_recorded_filings(session: Session, company: Company) -> None:
    """Read the company's recorded filings (`fixtures/edgar/filings/`), as a backfill does
    (M7b S7): the database then holds the face lines and extension facts the fixture pipeline
    builds from, so the two paths give the same tables."""
    from bedrock.services.filings import ingest_filings

    from .fakes import FakeFilings

    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=FakeFilings())
    ingest_filings(session, sources, company, limit=None)
