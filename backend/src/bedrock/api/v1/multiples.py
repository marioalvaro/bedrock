from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.multiples import MultipleOut, MultiplesOut
from bedrock.services import ratios as service

router = APIRouter(tags=["multiples"])


@router.get("/companies/{ticker}/multiples")
def get_multiples(
    basis: Literal["reported", "normalized"] = "reported",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> MultiplesOut:
    close, rows = service.multiples(session, company, basis)
    return MultiplesOut(
        ticker=company.ticker,
        basis=basis,
        price=None if close is None else close[1],
        price_date=None if close is None else close[0],
        rows=[MultipleOut.from_summary(s) for s in rows],
    )
