from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import prices as prices_repo
from bedrock.services.errors import CompanyNotFound
from bedrock.services.mappings import sync_mappings


@dataclass(frozen=True)
class RefreshResult:
    ticker: str
    new_filings: int
    new_facts: int
    new_prices: int
    last_refreshed_at: datetime
    warnings: list[str]


def refresh_company(
    session: Session, sources: Sources, ticker: str, now: datetime
) -> RefreshResult:
    """Load what EDGAR and the price source have that is not stored yet, and commit.

    A price failure is a warning; an EDGAR failure is raised, and nothing is kept (not even the
    mapping sync), so a failed refresh leaves the database as it was."""
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    try:
        sync_mappings(session)
        payload = sources.edgar.fetch(CompanyRef(company.ticker, company.cik), None)
        new_filings, new_facts = facts_repo.insert_parsed(
            session, company, parse_companyfacts(payload.companyfacts)
        )

        warnings: list[str] = []
        new_prices = 0
        try:
            since = prices_repo.last_date(session, company.id)
            # Nothing can be newer than today, and the source rejects a start date after "now".
            if since is None or since < now.astimezone(UTC).date():
                rows = sources.prices.fetch(CompanyRef(company.ticker, company.cik), since).rows
                new_prices = prices_repo.insert_new(session, company.id, rows)
        except SourceUnavailable as error:
            warnings.append(f"prices not updated: {error}")

        # SQLite keeps no time zone, so the column holds UTC without one.
        company.last_refreshed_at = now.astimezone(UTC).replace(tzinfo=None)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return RefreshResult(company.ticker, new_filings, new_facts, new_prices, now, warnings)
