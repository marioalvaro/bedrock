from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.services.errors import CompanyNotFound
from bedrock.services.mappings import sync_mappings
from bedrock.services.prices import update_prices


@dataclass(frozen=True)
class RefreshResult:
    ticker: str
    new_filings: int
    new_facts: int
    new_prices: int
    new_splits: int
    last_refreshed_at: datetime
    warnings: list[str]


def refresh_company(
    session: Session, sources: Sources, ticker: str, now: datetime
) -> RefreshResult:
    """Load what EDGAR and the price source have that is not stored yet, and commit. A manual
    company has no EDGAR data: only its prices are loaded.

    A price (or split) failure is a warning; an EDGAR failure is raised, and nothing is kept (not
    even the mapping sync), so a failed refresh leaves the database as it was."""
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    try:
        sync_mappings(session)
        new_filings = new_facts = 0
        if company.source == "sec":
            payload = sources.edgar.fetch(CompanyRef(company.ticker, company.cik), None)
            new_filings, new_facts = facts_repo.insert_parsed(
                session, company, parse_companyfacts(payload.companyfacts)
            )

        warnings: list[str] = []
        new_prices = 0
        new_splits = 0
        try:
            update = update_prices(session, sources.prices, company, now)
            new_prices, new_splits = update.new_prices, update.new_splits
        except SourceUnavailable as error:
            warnings.append(f"prices and splits not updated: {error}")

        # SQLite keeps no time zone, so the column holds UTC without one.
        company.last_refreshed_at = now.astimezone(UTC).replace(tzinfo=None)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return RefreshResult(
        company.ticker, new_filings, new_facts, new_prices, new_splits, now, warnings
    )
