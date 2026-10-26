from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.ratios import RatioCellOut, RatiosOut
from bedrock.services import ratios as service

router = APIRouter(tags=["ratios"])


@router.get("/companies/{ticker}/ratios/cell")
def get_ratio_cell(
    freq: Literal["annual", "ttm"] = Query(),
    code: str = Query(),
    fiscal_year: int = Query(),
    fiscal_period: str = Query(),
    basis: Literal["reported", "normalized"] = "reported",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> RatioCellOut:
    cell = service.ratio_cell(session, company, freq, basis, code, fiscal_year, fiscal_period)
    return RatioCellOut.from_explanation(cell)


@router.get("/companies/{ticker}/ratios")
def get_ratios(
    freq: Literal["annual", "ttm"] = Query(),
    basis: Literal["reported", "normalized"] = "reported",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> RatiosOut:
    table = service.ratios(session, company, freq, basis)
    return RatiosOut.from_table(table, ticker=company.ticker, basis=basis)
