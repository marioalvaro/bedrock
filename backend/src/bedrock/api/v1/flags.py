from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.analysis import (
    CapitalAllocationOut,
    FlagsOut,
    OffBalanceItemIn,
    OffBalanceItemOut,
)
from bedrock.services import analysis as service

router = APIRouter(tags=["analysis"])


@router.get("/companies/{ticker}/flags")
def get_flags(
    freq: Literal["annual", "ttm"] = Query(),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> FlagsOut:
    return FlagsOut.from_flags(service.flags(session, company, freq), ticker=company.ticker)


@router.get("/companies/{ticker}/capital-allocation")
def get_capital_allocation(
    freq: Literal["annual", "ttm"] = Query(),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> CapitalAllocationOut:
    table = service.capital_allocation(session, company, freq)
    return CapitalAllocationOut.from_table(table, ticker=company.ticker)


@router.get("/companies/{ticker}/off-balance-items")
def list_off_balance_items(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> list[OffBalanceItemOut]:
    return [
        OffBalanceItemOut.from_model(i) for i in service.list_off_balance_items(session, company)
    ]


@router.post("/companies/{ticker}/off-balance-items", status_code=201)
def create_off_balance_item(
    body: OffBalanceItemIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> OffBalanceItemOut:
    return OffBalanceItemOut.from_model(
        service.create_off_balance_item(session, company, body.to_input(), now)
    )


@router.put("/companies/{ticker}/off-balance-items/{item_id}")
def update_off_balance_item(
    item_id: int,
    body: OffBalanceItemIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> OffBalanceItemOut:
    return OffBalanceItemOut.from_model(
        service.update_off_balance_item(session, company, item_id, body.to_input(), now)
    )


@router.delete("/companies/{ticker}/off-balance-items/{item_id}", status_code=204)
def delete_off_balance_item(
    item_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_off_balance_item(session, company, item_id)
