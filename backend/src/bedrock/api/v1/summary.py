from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.summary import CompanySummaryOut
from bedrock.services.summary import company_summary

router = APIRouter(tags=["summary"])


@router.get("/companies/{ticker}/summary")
def get_summary(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> CompanySummaryOut:
    """The Overview summary, computed on read: a block without data is null or empty and says
    why in `warnings`."""
    return CompanySummaryOut.from_summary(company.ticker, company_summary(session, company))
