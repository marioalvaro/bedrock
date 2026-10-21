"""Markdown notes of a followed company, linked to a cell, a line or a period (FR-NOTE-01/02)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.note import Note
from bedrock.repositories import notes as repo
from bedrock.repositories.notes import LinkCount
from bedrock.services.errors import InvalidNote, NoteNotFound
from bedrock.services.statements import canonical_items

__all__ = [
    "BODY_LIMIT",
    "LinkCount",
    "NoteInput",
    "create_note",
    "delete_note",
    "label_of",
    "link_counts",
    "list_notes",
    "update_note",
]

BODY_LIMIT = 20_000  # characters, once stripped
YEAR_RANGE = (1000, 9999)  # four digits, as the segment import grammar
PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4")


@dataclass(frozen=True)
class NoteInput:
    body_md: str
    canonical_code: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    note_date: date | None  # None: today (UTC) on create, the stored date on update


def label_of(code: str | None) -> str | None:
    """The line's label, or None for a note with no line."""
    return next((i.label for i in canonical_items() if i.code == code), None)


def list_notes(
    session: Session,
    company: Company,
    code: str | None,
    fiscal_year: int | None,
    fiscal_period: str | None,
) -> list[Note]:
    """Newest `note_date` first. A filter by `code`, by period or by both (see
    `repositories/notes.py::list_for`); a period is `fiscal_year` and `fiscal_period` together.
    Raises InvalidNote for only one of them."""
    _check_period(fiscal_year, fiscal_period)
    period = None if fiscal_year is None or fiscal_period is None else (fiscal_year, fiscal_period)
    return repo.list_for(session, company.id, code, period)


def link_counts(session: Session, company: Company) -> list[LinkCount]:
    """The distinct links of the company's notes with their counts (drives the grid markers)."""
    return repo.link_counts(session, company.id)


def create_note(session: Session, company: Company, data: NoteInput, now: datetime) -> Note:
    """Validates, stores (body stripped) and commits. Raises InvalidNote for a blank body or one
    over `BODY_LIMIT`, an unknown line code, or a year without a period (or the reverse)."""
    body = _validate(data)
    stamp = _naive_utc(now)
    added = repo.add(
        session,
        Note(
            company_id=company.id,
            body_md=body,
            canonical_code=data.canonical_code,
            fiscal_year=data.fiscal_year,
            fiscal_period=data.fiscal_period,
            note_date=data.note_date or _utc(now).date(),
            created_at=stamp,
            updated_at=stamp,
        ),
    )
    note_id = added.id
    session.commit()
    return _stored(session, company, note_id)


def update_note(
    session: Session, company: Company, note_id: int, data: NoteInput, now: datetime
) -> Note:
    """Replaces the body and the link (no link given: the note is unlinked) and, when given, the
    date, under the rules of `create_note`. Raises NoteNotFound for an unknown id (or another
    company's)."""
    stored = _stored(session, company, note_id)
    stored.body_md = _validate(data)
    stored.canonical_code = data.canonical_code
    stored.fiscal_year = data.fiscal_year
    stored.fiscal_period = data.fiscal_period
    if data.note_date is not None:
        stored.note_date = data.note_date
    stored.updated_at = _naive_utc(now)
    session.commit()
    return _stored(session, company, note_id)


def delete_note(session: Session, company: Company, note_id: int) -> None:
    repo.delete(session, _stored(session, company, note_id))
    session.commit()


def _validate(data: NoteInput) -> str:
    body = data.body_md.strip()
    if not body:
        raise InvalidNote("The note must not be blank")
    if len(body) > BODY_LIMIT:
        raise InvalidNote(f"The note must be at most {BODY_LIMIT:,} characters")
    if data.canonical_code is not None and label_of(data.canonical_code) is None:
        raise InvalidNote(f"Unknown line item {data.canonical_code!r}")
    _check_period(data.fiscal_year, data.fiscal_period)
    if data.fiscal_year is not None and not YEAR_RANGE[0] <= data.fiscal_year <= YEAR_RANGE[1]:
        raise InvalidNote(f"The fiscal year must be between {YEAR_RANGE[0]} and {YEAR_RANGE[1]}")
    return body


def _check_period(fiscal_year: int | None, fiscal_period: str | None) -> None:
    if (fiscal_year is None) != (fiscal_period is None):
        raise InvalidNote("Give the fiscal year and the fiscal period together, or neither")
    if fiscal_period is not None and fiscal_period not in PERIODS:
        raise InvalidNote(f"The fiscal period must be one of {PERIODS}")


def _stored(session: Session, company: Company, note_id: int) -> Note:
    stored = repo.get(session, company.id, note_id)
    if stored is None:
        raise NoteNotFound(str(note_id))
    return stored


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment
