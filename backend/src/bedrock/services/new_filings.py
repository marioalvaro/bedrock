"""New-filing detection (M7c, FR-DATA-23; docs/erd/data.md "New-filing detection"): once a day
each SEC company's EDGAR filing index is read and the 10-Ks and 10-Qs not loaded yet are marked.
Nothing is ingested here: the Refresh button stays the one way filings are read."""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from bedrock.ingest.parse import unseen_filings
from bedrock.ingest.protocol import (
    CompanyRef,
    SourceNotConfigured,
    SourceUnavailable,
    SubmissionsLike,
)
from bedrock.models.company import Company
from bedrock.models.pending_filing import PendingFiling
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import pending_filings as pending_repo

# The scheduled loop runs eight times a weekday; this makes it one index read per company a day.
FILINGS_CHECK_INTERVAL = timedelta(hours=20)


def filings_due(checked_at: datetime | None, now: datetime) -> bool:
    """Whether the index is to be read: never checked, or checked at least the interval ago.
    `checked_at` is naive UTC (as stored); `now` is aware."""
    if checked_at is None:
        return True
    return _naive_utc(now) - checked_at >= FILINGS_CHECK_INTERVAL


def check_company(
    session: Session, source: SubmissionsLike, company: Company, now: datetime
) -> int:
    """Read the company's index, make its pending rows the unseen 10-Ks and 10-Qs, record the
    check time and commit; returns the number pending. A manual company is skipped (0, no call).
    A source error is raised with nothing written."""
    if company.cik is None:
        return 0
    recent = source.recent_filings(CompanyRef(company.ticker, company.cik))
    unseen = unseen_filings(
        recent,
        facts_repo.filing_accessions(session, company.id),
        facts_repo.latest_filing_date(session, company.id),
    )
    stamp = _naive_utc(now)
    pending_repo.replace(session, company.id, unseen, stamp)
    company.filings_checked_at = stamp
    session.commit()
    return len(unseen)


def check_all(session: Session, source: SubmissionsLike, now: datetime) -> list[str]:
    """Check every due SEC company, in ticker order, one commit each. A failing company is a
    warning "<TICKER>: filings not checked: …"; its rows and check time are kept, so it is tried
    again at the next run."""
    warnings: list[str] = []
    for company in companies_repo.list_all(session):
        if company.source != "sec" or not filings_due(company.filings_checked_at, now):
            continue
        try:
            check_company(session, source, company, now)
        except (SourceUnavailable, SourceNotConfigured) as error:
            session.rollback()
            warnings.append(f"{company.ticker}: filings not checked: {error}")
    return warnings


def clear_ingested(session: Session, company: Company) -> None:
    """Delete the company's pending rows whose filing is now stored. No commit: the refresh calls
    it inside its own transaction."""
    pending_repo.delete_ingested(session, company.id)


def pending(session: Session, company_ids: Collection[int]) -> dict[int, list[PendingFiling]]:
    """Company id → its pending filings, newest `filed_at` first, in one query."""
    return pending_repo.for_companies(session, company_ids)


def _naive_utc(when: datetime) -> datetime:
    # SQLite keeps no time zone, so the columns hold UTC without one.
    return when.astimezone(UTC).replace(tzinfo=None)
