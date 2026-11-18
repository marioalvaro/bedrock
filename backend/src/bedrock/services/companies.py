from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from bedrock.analysis.multiples import KeyStats
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.models.pending_filing import PendingFiling
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import filing_lines as lines_repo
from bedrock.repositories.companies import DeletionCounts
from bedrock.services import new_filings as new_filings_service
from bedrock.services.errors import (
    CompanyArchived,
    CompanyExists,
    CompanyNotArchived,
    CompanyNotFound,
)
from bedrock.services.refresh import refresh_company
from bedrock.services.statements import company_key_stats

__all__ = [
    "CompanyArchived",
    "CompanyExists",
    "CompanyNotArchived",
    "CompanyNotFound",
    "CompanyView",
    "DeletionCounts",
    "add_company",
    "add_manual_company",
    "archive_company",
    "deletion_impact",
    "get_company",
    "list_companies",
    "remove_company",
    "restore_company",
]


@dataclass(frozen=True)
class CompanyView:
    company: Company
    stats: KeyStats
    filings_parsed: int = 0  # filings of the four forms whose XBRL is read (M7b S6)
    filings_total: int = 0
    # 10-Ks and 10-Qs EDGAR lists that are not loaded yet, newest first (M7c, FR-DATA-23)
    new_filings: list[PendingFiling] = field(default_factory=list)


def list_companies(session: Session, archived: bool = False) -> list[CompanyView]:
    """The followed companies, or with `archived` the archived ones only, by ticker."""
    companies = companies_repo.list_followed(session, archived)
    ids = [c.id for c in companies]
    progress = lines_repo.xbrl_progress(session, ids)
    pending = new_filings_service.pending(session, ids)
    return [
        _view(session, company, progress[company.id], pending[company.id]) for company in companies
    ]


def get_company(session: Session, ticker: str) -> CompanyView:
    return _view(session, _followed(session, ticker))


def add_company(session: Session, sources: Sources, ticker: str, now: datetime) -> CompanyView:
    """Follow a company: resolve it, insert it and load its data. All or nothing: if the first
    load fails nothing is kept, so there is never a followed company with no data."""
    symbol = ticker.strip().upper()
    _check_new(session, symbol)
    profile = sources.edgar.resolve(symbol)
    # Two tickers can share a CIK (share classes): one followed company per filer. An archived
    # filer is named by its stored ticker, the one to restore.
    filer = companies_repo.get_by_cik(session, profile.cik)
    if filer is not None:
        raise (
            CompanyArchived(filer.ticker)
            if filer.archived_at is not None
            else CompanyExists(symbol)
        )
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
    session.flush()
    refresh_company(session, sources, profile.ticker, now)  # commits, or rolls back and raises
    return _view(session, company)


def add_manual_company(
    session: Session, ticker: str, name: str, fiscal_year_end_month: int, sic: str | None
) -> CompanyView:
    """Follow a company SEC does not cover: no CIK, no EDGAR data, filled by statement import. The
    tickers of both sources share one namespace."""
    symbol = ticker.strip().upper()
    _check_new(session, symbol)
    company = Company(
        ticker=symbol,
        cik=None,
        name=name.strip(),
        fiscal_year_end_month=fiscal_year_end_month,
        currency="USD",
        source="manual",
        sic=sic,
        last_refreshed_at=None,
    )
    session.add(company)
    session.commit()
    return _view(session, company)


def archive_company(session: Session, ticker: str, now: datetime) -> None:
    """Archive a company: it leaves the followed list and the scheduler, its data is kept. An
    archived company keeps the time it was first archived."""
    company = _followed(session, ticker)
    if company.archived_at is None:
        company.archived_at = now.astimezone(UTC).replace(tzinfo=None)  # naive UTC, as stored
        session.commit()


def restore_company(session: Session, ticker: str) -> None:
    """Follow an archived company again; nothing is re-ingested. A no-op on a followed one."""
    company = _followed(session, ticker)
    if company.archived_at is not None:
        company.archived_at = None
        session.commit()


def deletion_impact(session: Session, ticker: str) -> tuple[Company, DeletionCounts]:
    """What deleting the company permanently removes, as row counts per kind."""
    company = _followed(session, ticker)
    return company, companies_repo.deletion_counts(session, company.id)


def remove_company(session: Session, ticker: str) -> None:
    """Delete an archived company permanently; the database cascades to its filings, facts,
    prices, overrides and everything else it owns. Raises CompanyNotArchived for a followed one:
    deletion is the second of two deliberate steps."""
    company = _followed(session, ticker)
    if company.archived_at is None:
        raise CompanyNotArchived(company.ticker)
    session.delete(company)
    session.commit()


def _check_new(session: Session, symbol: str) -> None:
    stored = companies_repo.get_by_ticker(session, symbol)
    if stored is not None:
        raise CompanyArchived(symbol) if stored.archived_at is not None else CompanyExists(symbol)


def _followed(session: Session, ticker: str) -> Company:
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    return company


def _view(
    session: Session,
    company: Company,
    progress: tuple[int, int] | None = None,
    pending: list[PendingFiling] | None = None,
) -> CompanyView:
    parsed, total = progress or lines_repo.xbrl_progress(session, [company.id])[company.id]
    if pending is None:
        pending = new_filings_service.pending(session, [company.id])[company.id]
    return CompanyView(company, company_key_stats(session, company), parsed, total, pending)
