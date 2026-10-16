from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.adjustments import AdjustmentIn, AdjustmentOut
from bedrock.services import adjustments as service

router = APIRouter(tags=["adjustments"])


@router.get("/companies/{ticker}/adjustments")
def list_adjustments(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> list[AdjustmentOut]:
    return [AdjustmentOut.from_model(a) for a in service.list_adjustments(session, company)]


@router.post("/companies/{ticker}/adjustments", status_code=201)
def create_adjustment(
    body: AdjustmentIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> AdjustmentOut:
    return AdjustmentOut.from_model(
        service.create_adjustment(session, company, body.to_input(), now)
    )


@router.put("/companies/{ticker}/adjustments/{adjustment_id}")
def update_adjustment(
    adjustment_id: int,
    body: AdjustmentIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> AdjustmentOut:
    return AdjustmentOut.from_model(
        service.update_adjustment(session, company, adjustment_id, body.to_input(), now)
    )


@router.delete("/companies/{ticker}/adjustments/{adjustment_id}", status_code=204)
def delete_adjustment(
    adjustment_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_adjustment(session, company, adjustment_id)
