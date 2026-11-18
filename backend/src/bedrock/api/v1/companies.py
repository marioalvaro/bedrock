from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from bedrock.api.deps import (
    get_backfills,
    get_clock,
    get_session,
    get_session_factory,
    get_sources,
)
from bedrock.ingest.sources import Sources
from bedrock.schemas.company import (
    CompanyCreate,
    CompanyListItem,
    DeletionImpactOut,
    ManualCompanyCreate,
)
from bedrock.schemas.refresh import BackfillStartedOut, RefreshResultOut
from bedrock.services import companies as service
from bedrock.services.filings import BackfillRunner
from bedrock.services.refresh import refresh_company

router = APIRouter(tags=["companies"])


@router.get("/companies")
def get_companies(
    archived: bool = False, session: Session = Depends(get_session)
) -> list[CompanyListItem]:
    """The followed companies, or with `archived=true` the archived ones only."""
    return [CompanyListItem.from_view(v) for v in service.list_companies(session, archived)]


@router.post("/companies", status_code=201)
def add_company(
    body: CompanyCreate,
    session: Session = Depends(get_session),
    sources: Sources = Depends(get_sources),
    now: datetime = Depends(get_clock),
) -> CompanyListItem:
    return CompanyListItem.from_view(service.add_company(session, sources, body.ticker, now))


@router.post("/companies/manual", status_code=201)
def add_manual_company(
    body: ManualCompanyCreate, session: Session = Depends(get_session)
) -> CompanyListItem:
    return CompanyListItem.from_view(
        service.add_manual_company(
            session, body.ticker, body.name, body.fiscal_year_end_month, body.sic
        )
    )


@router.get("/companies/{ticker}")
def get_company(ticker: str, session: Session = Depends(get_session)) -> CompanyListItem:
    return CompanyListItem.from_view(service.get_company(session, ticker))


@router.delete("/companies/{ticker}", status_code=204)
def remove_company(ticker: str, session: Session = Depends(get_session)) -> None:
    """Delete an archived company and everything it owns; 409 for a company not archived."""
    service.remove_company(session, ticker)


@router.post("/companies/{ticker}/archive", status_code=204)
def archive_company(
    ticker: str, session: Session = Depends(get_session), now: datetime = Depends(get_clock)
) -> None:
    service.archive_company(session, ticker, now)


@router.post("/companies/{ticker}/restore", status_code=204)
def restore_company(ticker: str, session: Session = Depends(get_session)) -> None:
    service.restore_company(session, ticker)


@router.get("/companies/{ticker}/deletion-impact")
def deletion_impact(ticker: str, session: Session = Depends(get_session)) -> DeletionImpactOut:
    company, counts = service.deletion_impact(session, ticker)
    return DeletionImpactOut.from_counts(company.ticker, counts)


@router.post("/companies/{ticker}/refresh")
def refresh(
    ticker: str,
    session: Session = Depends(get_session),
    sources: Sources = Depends(get_sources),
    now: datetime = Depends(get_clock),
) -> RefreshResultOut:
    return RefreshResultOut.from_result(refresh_company(session, sources, ticker, now))


@router.post("/companies/{ticker}/backfill-filings", status_code=202)
def backfill_filings(
    ticker: str,
    session: Session = Depends(get_session),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    sources: Sources = Depends(get_sources),
    backfills: BackfillRunner = Depends(get_backfills),
) -> BackfillStartedOut:
    """Read the XBRL of every filing not read yet, in a worker thread; 409 while one runs."""
    company = backfills.start(session, session_factory, sources, ticker)
    return BackfillStartedOut(ticker=company.ticker)
