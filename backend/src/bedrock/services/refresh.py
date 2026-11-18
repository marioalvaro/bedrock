import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.services import consensus as consensus_service
from bedrock.services import new_filings as new_filings_service
from bedrock.services.errors import CompanyNotFound
from bedrock.services.filings import ingest_filings
from bedrock.services.mappings import sync_mappings
from bedrock.services.prices import update_prices

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshResult:
    ticker: str
    new_filings: int
    new_facts: int
    new_prices: int
    new_splits: int
    last_refreshed_at: datetime
    warnings: list[str]
    new_filing_lines: int = 0  # face-statement lines read from the filings' own XBRL (M7b S6)


# A refresh reads at most this many filings' XBRL: a new filing, or the newest year on a first
# load. `backfill-filings` reads the rest.
REFRESH_FILINGS_LIMIT = 4


def refresh_company(
    session: Session, sources: Sources, ticker: str, now: datetime
) -> RefreshResult:
    """Load what EDGAR and the price source have that is not stored yet, and commit. A manual
    company has no EDGAR data: only its prices are loaded.

    A price (or split) failure is a warning; an EDGAR failure is raised, and nothing is kept (not
    even the mapping sync), so a failed refresh leaves the database as it was. After that commit,
    the newest filings not read yet are read for their XBRL (`ingest_filings`, which commits
    filing by filing); a failure there is a warning, never a rollback. The analyst consensus is
    fetched last (`refresh_consensus`, which commits), so a company followed or refreshed between
    two scheduled runs has it; a failure there is a warning too, and the stored rows are kept."""
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
            # A marked filing goes when it is stored, in this transaction (M7c, FR-DATA-23).
            new_filings_service.clear_ingested(session, company)

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

    new_filing_lines = 0
    try:
        filings = ingest_filings(session, sources, company, limit=REFRESH_FILINGS_LIMIT)
        new_filing_lines = filings.new_lines
        warnings.extend(filings.warnings)
    except Exception as error:  # the refresh is committed: any filings failure is a warning
        session.rollback()
        logger.exception("filings of %s not read", company.ticker)
        warnings.append(f"filings not read: {error}")
    if sources.consensus is not None:
        try:
            consensus_service.refresh_consensus(session, sources.consensus, company, now)
        except SourceUnavailable as error:
            session.rollback()
            warnings.append(f"consensus not updated: {error}")
        except Exception as error:  # the refresh is committed: never a 500 for the consensus
            session.rollback()
            logger.exception("consensus of %s not updated", company.ticker)
            warnings.append(f"consensus not updated: {error}")
    return RefreshResult(
        company.ticker,
        new_filings,
        new_facts,
        new_prices,
        new_splits,
        now,
        warnings,
        new_filing_lines,
    )
