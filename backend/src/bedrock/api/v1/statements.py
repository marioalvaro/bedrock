from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.schemas.statements import CellDetailOut, MappingGapsOut, StatementOut
from bedrock.services import statements as service
from bedrock.services.errors import CompanyNotFound

router = APIRouter(tags=["statements"])


def followed_company(ticker: str, session: Session = Depends(get_session)) -> Company:
    company = companies_repo.get_by_ticker(session, ticker.strip().upper())
    if company is None:
        raise CompanyNotFound(ticker)
    return company


@router.get("/companies/{ticker}/statements")
def get_statement(
    statement: Literal["IS", "BS", "CF"] = Query(alias="type"),
    freq: Literal["annual", "quarterly", "ttm"] = Query(),
    basis: Literal["reported", "normalized"] = "reported",
    common_size_base: Literal["total", "parent"] = "total",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> StatementOut:
    try:
        table = service.build_statements(session, company, statement, freq, basis, common_size_base)
    except ValueError as error:  # a TTM balance sheet
        raise HTTPException(status_code=422, detail=str(error)) from error
    return StatementOut.from_table(
        table,
        ticker=company.ticker,
        statement=statement,
        freq=freq,
        basis=basis,
        currency=company.currency,
    )


@router.get("/companies/{ticker}/statements/cell")
def get_cell(
    code: str,
    fiscal_year: int,
    fiscal_period: str,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> CellDetailOut:
    cell = service.cell_detail(session, company, code, fiscal_year, fiscal_period)
    return CellDetailOut.from_explanation(cell)


@router.get("/companies/{ticker}/mapping-gaps")
def get_mapping_gaps(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> MappingGapsOut:
    return MappingGapsOut.from_gaps(service.mapping_gaps(session, company))
