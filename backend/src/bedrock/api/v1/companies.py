from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session, get_sources
from bedrock.ingest.sources import Sources
from bedrock.schemas.company import CompanyCreate, CompanyListItem
from bedrock.schemas.refresh import RefreshResultOut
from bedrock.services import companies as service
from bedrock.services.refresh import refresh_company

router = APIRouter(tags=["companies"])


@router.get("/companies")
def get_companies(session: Session = Depends(get_session)) -> list[CompanyListItem]:
    return [CompanyListItem.from_view(v) for v in service.list_companies(session)]


@router.post("/companies", status_code=201)
def add_company(
    body: CompanyCreate,
    session: Session = Depends(get_session),
    sources: Sources = Depends(get_sources),
    now: datetime = Depends(get_clock),
) -> CompanyListItem:
    return CompanyListItem.from_view(service.add_company(session, sources, body.ticker, now))


@router.get("/companies/{ticker}")
def get_company(ticker: str, session: Session = Depends(get_session)) -> CompanyListItem:
    return CompanyListItem.from_view(service.get_company(session, ticker))


@router.delete("/companies/{ticker}", status_code=204)
def remove_company(ticker: str, session: Session = Depends(get_session)) -> None:
    service.remove_company(session, ticker)


@router.post("/companies/{ticker}/refresh")
def refresh(
    ticker: str,
    session: Session = Depends(get_session),
    sources: Sources = Depends(get_sources),
    now: datetime = Depends(get_clock),
) -> RefreshResultOut:
    return RefreshResultOut.from_result(refresh_company(session, sources, ticker, now))
