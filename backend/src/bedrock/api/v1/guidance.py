from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.guidance import GuidanceEntryOut, GuidanceIn, GuidanceOut, MetricChoiceOut
from bedrock.services import guidance as service

router = APIRouter(tags=["guidance"])


@router.get("/companies/{ticker}/guidance/metrics")
def list_metrics(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> list[MetricChoiceOut]:
    return [MetricChoiceOut.from_choice(c) for c in service.metric_choices(session, company)]


@router.get("/companies/{ticker}/guidance")
def get_guidance(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> GuidanceOut:
    return GuidanceOut.from_log(company.ticker, service.guidance_log(session, company))


@router.post("/companies/{ticker}/guidance", status_code=201)
def create_entry(
    body: GuidanceIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> GuidanceEntryOut:
    return GuidanceEntryOut.from_logged(
        service.create_entry(session, company, body.to_input(), now)
    )


@router.put("/companies/{ticker}/guidance/{guidance_id}")
def update_entry(
    guidance_id: int,
    body: GuidanceIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> GuidanceEntryOut:
    return GuidanceEntryOut.from_logged(
        service.update_entry(session, company, guidance_id, body.to_input(), now)
    )


@router.delete("/companies/{ticker}/guidance/{guidance_id}", status_code=204)
def delete_entry(
    guidance_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_entry(session, company, guidance_id)
