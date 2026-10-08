from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from bedrock.analysis.multiples import KeyStats
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.services.errors import CompanyExists, CompanyNotFound
from bedrock.services.refresh import refresh_company
from bedrock.services.statements import company_key_stats

__all__ = [
    "CompanyExists",
    "CompanyNotFound",
    "CompanyView",
    "add_company",
    "get_company",
    "list_companies",
    "remove_company",
]


@dataclass(frozen=True)
class CompanyView:
    company: Company
    stats: KeyStats


def list_companies(session: Session) -> list[CompanyView]:
    return [_view(session, company) for company in companies_repo.list_all(session)]


def get_company(session: Session, ticker: str) -> CompanyView:
    return _view(session, _followed(session, ticker))


def add_company(session: Session, sources: Sources, ticker: str, now: datetime) -> CompanyView:
    """Follow a company: resolve it, insert it and load its data. All or nothing: if the first
    load fails nothing is kept, so there is never a followed company with no data."""
    symbol = ticker.strip().upper()
    if companies_repo.get_by_ticker(session, symbol) is not None:
        raise CompanyExists(symbol)
    profile = sources.edgar.resolve(symbol)
    # Two tickers can share a CIK (share classes): one followed company per filer.
    if companies_repo.get_by_cik(session, profile.cik) is not None:
        raise CompanyExists(symbol)
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


def remove_company(session: Session, ticker: str) -> None:
    """Unfollow a company; the database cascades to its filings, facts, prices and overrides."""
    session.delete(_followed(session, ticker))
    session.commit()


def _followed(session: Session, ticker: str) -> Company:
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    return company


def _view(session: Session, company: Company) -> CompanyView:
    return CompanyView(company, company_key_stats(session, company))
