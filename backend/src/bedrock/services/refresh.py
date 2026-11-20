import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from bedrock.backtest.snapshot import incoming_reports
from bedrock.core.clock import naive_utc
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.ingest.parse import ParsedFacts, parse_companyfacts
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import pending_filings as pending_repo
from bedrock.services import consensus as consensus_service
from bedrock.services import snapshots as snapshots_service
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
    snapshot_id: int | None = None  # the snapshot taken before a new 10-K or 10-Q (M7c)


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
    two scheduled runs has it; a failure there is a warning too, and the stored rows are kept.

    Before a new 10-K or 10-Q is stored, the default scenario is snapshotted (`_snapshot_step`,
    which commits on its own and never fails the refresh; docs/erd/accountability.md "Automatic
    snapshots")."""
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    warnings: list[str] = []
    snapshot_id: int | None = None
    try:
        parsed: ParsedFacts | None = None
        if company.source == "sec":
            # The fetch and the parse write nothing, so they go first.
            payload = sources.edgar.fetch(CompanyRef(company.ticker, company.cik), None)
            parsed = parse_companyfacts(payload.companyfacts)
            snapshot_id = _snapshot_step(session, company, parsed, now, warnings)
        sync_mappings(session)
        new_filings, new_facts = (0, 0) if parsed is None else _store(session, company, parsed)

        new_prices = 0
        new_splits = 0
        try:
            update = update_prices(session, sources.prices, company, now)
            new_prices, new_splits = update.new_prices, update.new_splits
        except SourceUnavailable as error:
            warnings.append(f"prices and splits not updated: {error}")

        company.last_refreshed_at = naive_utc(now)
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
        snapshot_id,
    )


def _store(session: Session, company: Company, parsed: ParsedFacts) -> tuple[int, int]:
    """Inserts the parsed filings and facts (new filings, new facts) and unmarks the pending
    filings now stored, in the refresh transaction (M7c, FR-DATA-23). No commit."""
    counts = facts_repo.insert_parsed(session, company, parsed)
    pending_repo.delete_ingested(session, company.id)
    return counts


def _snapshot_step(
    session: Session, company: Company, parsed: ParsedFacts, now: datetime, warnings: list[str]
) -> int | None:
    """Freezes the default scenario when `parsed` brings a 10-K or 10-Q not stored yet, on the
    data stored before it. A failure is a warning, with the session rolled back."""
    try:
        stored = facts_repo.filing_accessions(session, company.id)
        incoming = incoming_reports(parsed.filings, stored)
        view = snapshots_service.snapshot_before(session, company, incoming, now)
    except ForecastUnavailable as unavailable:
        session.rollback()
        warnings.append(f"forecast not snapshotted: {unavailable.detail}")
        return None
    except Exception as error:  # a snapshot never blocks the refresh
        session.rollback()
        logger.exception("forecast of %s not snapshotted", company.ticker)
        warnings.append(f"forecast not snapshotted: {error}")
        return None
    return None if view is None else view.id
