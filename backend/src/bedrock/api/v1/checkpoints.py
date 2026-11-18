from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.checkpoints import CheckpointIn, CheckpointListOut, CheckpointOut
from bedrock.services import checkpoints as service

# Thesis checkpoints (FR-NOTE-03)
router = APIRouter(tags=["checkpoints"])


@router.get("/companies/{ticker}/checkpoints")
def list_checkpoints(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> CheckpointListOut:
    return CheckpointListOut.from_list(service.list_checkpoints(session, company))


@router.post("/companies/{ticker}/checkpoints", status_code=201)
def create_checkpoint(
    body: CheckpointIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> CheckpointOut:
    view = service.create_checkpoint(session, company, body.to_input(), now)
    return CheckpointOut.from_view(view)


@router.put("/companies/{ticker}/checkpoints/{checkpoint_id}")
def update_checkpoint(
    checkpoint_id: int,
    body: CheckpointIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> CheckpointOut:
    view = service.update_checkpoint(session, company, checkpoint_id, body.to_input(), now)
    return CheckpointOut.from_view(view)


@router.delete("/companies/{ticker}/checkpoints/{checkpoint_id}", status_code=204)
def delete_checkpoint(
    checkpoint_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_checkpoint(session, company, checkpoint_id)
