"""Filing-level XBRL ingestion (M7b S6, docs/erd/data-coverage.md "Flow"): each 10-K and 10-Q is
read once; its extension-taxonomy facts become raw facts (`source = 'filing'`) and the lines on the
face of its three statements are stored with their calculation parents."""

import logging
import threading
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from bedrock.ingest.parse import ParsedFacts
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.ingest.xbrl import (
    XBRL_PARSER_VERSION,
    StatementAnchors,
    XbrlError,
    is_standard_taxonomy,
    parse_filing,
)
from bedrock.mapping.config import DEFAULT_OVERRIDES_DIR, load_canonical_items, load_overrides
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import filing_lines as lines_repo
from bedrock.services.errors import BackfillRunning, CompanyNotFound

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilingsResult:
    parsed: int = 0
    absent: int = 0
    failed: int = 0
    new_facts: int = 0
    new_lines: int = 0
    warnings: list[str] = field(default_factory=list)


def statement_anchors(ticker: str) -> StatementAnchors:
    """The concepts that identify the statements for this company: each anchor item's defaults
    plus the concepts its override file adds."""
    items = load_canonical_items()
    overrides = load_overrides(DEFAULT_OVERRIDES_DIR, ticker, items)
    return StatementAnchors.from_concepts(
        {item.code: (*item.concepts, *overrides.get(item.code, ())) for item in items}
    )


def ingest_filings(
    session: Session,
    sources: Sources,
    company: Company,
    limit: int | None,
    *,
    reparse: bool = False,
) -> FilingsResult:
    """Read the company's filings of the four forms not tried yet, newest first, at most `limit`
    (None: all). With `reparse`, also re-read the `parsed` and `failed` ones (from the cache):
    their lines are rebuilt and their facts inserted where missing.

    One commit per filing. A fetch or parse failure marks the filing `failed`, adds a warning and
    goes on; a folder with no XBRL instance is `absent`. `SourceNotConfigured` is raised."""
    if sources.filings is None or company.cik is None:
        return FilingsResult()
    statuses: set[str | None] = {None, "parsed", "failed"} if reparse else {None}
    filings = lines_repo.filings_to_parse(session, company.id, statuses, limit)
    if not filings:
        return FilingsResult()
    anchors = statement_anchors(company.ticker)
    ref = CompanyRef(company.ticker, company.cik)
    counts = {"parsed": 0, "absent": 0, "failed": 0}
    new_facts = new_lines = 0
    warnings: list[str] = []
    for filing in filings:
        try:
            facts, lines = _read(session, sources, ref, company, filing, anchors)
        except (SourceUnavailable, XbrlError) as error:
            session.rollback()
            filing.xbrl_status = "failed"
            filing.xbrl_parser_version = None
            warnings.append(f"filing {filing.accession_no} ({filing.form}) not read: {error}")
        except Exception:
            session.rollback()
            raise
        else:
            new_facts += facts
            new_lines += lines
        counts[filing.xbrl_status or "failed"] += 1
        session.commit()
    return FilingsResult(
        counts["parsed"], counts["absent"], counts["failed"], new_facts, new_lines, warnings
    )


def _read(
    session: Session,
    sources: Sources,
    ref: CompanyRef,
    company: Company,
    filing: Filing,
    anchors: StatementAnchors,
) -> tuple[int, int]:
    """Fetch, parse and store one filing; returns (new facts, new lines)."""
    assert sources.filings is not None
    files = sources.filings.fetch(ref, filing.accession_no)
    lines_repo.delete_lines(session, filing.id)
    if not files:
        filing.xbrl_status = "absent"
        filing.xbrl_parser_version = None
        return 0, 0
    parsed = parse_filing(
        files,
        anchors,
        accession_no=filing.accession_no,
        fiscal_year=filing.fiscal_year,
        fiscal_period=filing.fiscal_period,
    )
    extension = [f for f in parsed.facts if not is_standard_taxonomy(f.taxonomy)]
    _, new_facts = facts_repo.insert_parsed(
        session, company, ParsedFacts(filings=[], facts=extension), source="filing"
    )
    new_lines = lines_repo.insert_lines(session, filing.id, parsed.lines)
    filing.xbrl_status = "parsed"
    filing.xbrl_parser_version = XBRL_PARSER_VERSION
    return new_facts, new_lines


def backfill_filings(
    session: Session, sources: Sources, ticker: str, *, reparse: bool = False
) -> FilingsResult:
    """Read every filing of a followed company not read yet (`bedrock backfill-filings`)."""
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    return ingest_filings(session, sources, company, limit=None, reparse=reparse)


class BackfillRunner:
    """Runs `backfill_filings` in a worker thread, one run per company at a time (the route's
    202). A failed run is logged; the filings it reached keep their status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[str, threading.Thread] = {}

    def start(
        self,
        session: Session,
        session_factory: sessionmaker[Session],
        sources: Sources,
        ticker: str,
    ) -> Company:
        """Start a backfill and return the company. Raises CompanyNotFound, or BackfillRunning
        while one runs for that company."""
        company = companies_repo.get_by_ticker(session, ticker.strip().upper())
        if company is None:
            raise CompanyNotFound(ticker)
        symbol = company.ticker
        with self._lock:
            if symbol in self._running:
                raise BackfillRunning(symbol)
            thread = threading.Thread(
                target=self._run,
                args=(session_factory, sources, symbol),
                name=f"backfill-filings-{symbol}",
                daemon=True,
            )
            self._running[symbol] = thread
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._running.pop(symbol, None)
            raise
        return company

    def join(self, ticker: str, timeout: float | None = None) -> None:
        """Wait for the company's run, if one is running (tests and shutdown)."""
        with self._lock:
            thread = self._running.get(ticker.upper())
        if thread is not None:
            thread.join(timeout)

    def _run(self, session_factory: sessionmaker[Session], sources: Sources, ticker: str) -> None:
        try:
            with session_factory() as session:
                result = backfill_filings(session, sources, ticker)
            logger.info(
                "backfill-filings %s: %d parsed, %d absent, %d failed",
                ticker,
                result.parsed,
                result.absent,
                result.failed,
            )
        except Exception:  # the thread's top level: nothing above it would see the error
            logger.exception("backfill-filings %s failed", ticker)
        finally:
            with self._lock:
                self._running.pop(ticker, None)
