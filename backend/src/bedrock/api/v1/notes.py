from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.models.note import Note
from bedrock.schemas.notes import FiscalPeriod, MetricKind, NoteIn, NoteLinkOut, NoteOut
from bedrock.services import notes as service

router = APIRouter(tags=["notes"])


def _out(session: Session, notes: list[Note]) -> list[NoteOut]:
    labels = service.note_labels(session, notes)
    return [NoteOut.from_model(n, labels[n.id]) for n in notes]


@router.get("/companies/{ticker}/notes")
def list_notes(
    code: str | None = None,
    fiscal_year: int | None = None,
    fiscal_period: FiscalPeriod | None = None,
    metric_kind: MetricKind | None = None,
    metric_code: str | None = None,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> list[NoteOut]:
    found = service.list_notes(
        session, company, code, fiscal_year, fiscal_period, metric_kind, metric_code
    )
    return _out(session, found)


# Declared before `/notes/{note_id}` so `links` is never read as an id.
@router.get("/companies/{ticker}/notes/links")
def list_links(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> list[NoteLinkOut]:
    return [NoteLinkOut.from_count(c) for c in service.link_counts(session, company)]


@router.post("/companies/{ticker}/notes", status_code=201)
def create_note(
    body: NoteIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> NoteOut:
    return _out(session, [service.create_note(session, company, body.to_input(), now)])[0]


@router.put("/companies/{ticker}/notes/{note_id}")
def update_note(
    note_id: int,
    body: NoteIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> NoteOut:
    stored = service.update_note(session, company, note_id, body.to_input(), now)
    return _out(session, [stored])[0]


@router.delete("/companies/{ticker}/notes/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_note(session, company, note_id)
