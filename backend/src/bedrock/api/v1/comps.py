from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.comps import CompsOut, CompsSetIn, CompsSetOut, PeerSuggestionOut
from bedrock.services import comps as service

router = APIRouter(tags=["comps"])


@router.get("/companies/{ticker}/comps-sets")
def list_sets(
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> list[CompsSetOut]:
    return [CompsSetOut.from_view(v) for v in service.list_sets(session, company)]


@router.post("/companies/{ticker}/comps-sets", status_code=201)
def create_set(
    body: CompsSetIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> CompsSetOut:
    return CompsSetOut.from_view(service.create_set(session, company, body.name, body.members, now))


@router.put("/companies/{ticker}/comps-sets/{set_id}")
def update_set(
    set_id: int,
    body: CompsSetIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> CompsSetOut:
    return CompsSetOut.from_view(
        service.update_set(session, company, set_id, body.name, body.members, now)
    )


@router.delete("/companies/{ticker}/comps-sets/{set_id}", status_code=204)
def delete_set(
    set_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_set(session, company, set_id)


@router.get("/companies/{ticker}/peer-suggestions")
def get_peer_suggestions(
    set_id: int | None = None,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> list[PeerSuggestionOut]:
    found = service.peer_suggestions(session, company, set_id)
    return [PeerSuggestionOut.from_suggestion(s) for s in found]


@router.get("/companies/{ticker}/comps-sets/{set_id}/comparison")
def get_comparison(
    set_id: int,
    basis: Literal["reported", "normalized"] = "reported",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> CompsOut:
    result = service.comparison(session, company, set_id, basis)
    return CompsOut.from_comparison(company.ticker, result)
