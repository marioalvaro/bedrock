"""Prices-only refresh (docs/erd/data.md "Scheduled refresh"): the scheduler's hourly job, and
the price step of a full refresh."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from bedrock.ingest.protocol import CompanyRef, PricesLike, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import corporate_actions as actions_repo
from bedrock.repositories import prices as prices_repo


@dataclass(frozen=True)
class PricesUpdate:
    new_prices: int
    new_splits: int


@dataclass
class PricesRefreshResult:
    new_prices: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def update_prices(
    session: Session, prices: PricesLike, company: Company, now: datetime
) -> PricesUpdate:
    """Fetch from the last stored day on (re-reading it: during the session it holds the latest
    quote, after the close the final one) and upsert; the split history comes with every fetch.
    Raises SourceUnavailable. Does not commit."""
    last = prices_repo.last_date(session, company.id)
    since = None if last is None else last - timedelta(days=1)
    quotes = prices.fetch(CompanyRef(company.ticker, company.cik), since)
    new_prices = prices_repo.upsert(session, company.id, quotes.rows)
    new_splits = actions_repo.insert_new(session, company.id, quotes.splits)
    return PricesUpdate(new_prices, new_splits)


def refresh_all_prices(session: Session, sources: Sources, now: datetime) -> PricesRefreshResult:
    """Every followed company's prices (archived ones left out), committed one company at a
    time; a company whose fetch fails is a warning and the others are kept."""
    result = PricesRefreshResult()
    for company in companies_repo.list_followed(session):
        try:
            update = update_prices(session, sources.prices, company, now)
            session.commit()
        except SourceUnavailable as error:
            session.rollback()
            result.warnings.append(f"{company.ticker}: prices not updated: {error}")
            continue
        result.new_prices[company.ticker] = update.new_prices
    return result
