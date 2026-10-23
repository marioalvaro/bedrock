"""Markdown notes of a followed company, linked to a cell, a line or a period (FR-NOTE-01/02)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from bedrock.analysis.capital_allocation import CAPITAL_METRICS
from bedrock.models.company import Company
from bedrock.models.note import Note
from bedrock.ratios.registry import RATIOS
from bedrock.repositories import notes as repo
from bedrock.repositories.notes import LinkCount
from bedrock.services import qoe
from bedrock.services.errors import InvalidNote, NoteNotFound
from bedrock.services.statements import canonical_items, fiscal_periods

__all__ = [
    "BODY_LIMIT",
    "LinkCount",
    "NoteInput",
    "create_note",
    "delete_note",
    "label_of",
    "link_counts",
    "list_notes",
    "note_labels",
    "update_note",
]

BODY_LIMIT = 20_000  # characters, once stripped
YEAR_RANGE = (1000, 9999)  # four digits, as the segment import grammar
PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4")
METRIC_KINDS = ("ratio", "capital", "quality")


@dataclass(frozen=True)
class NoteInput:
    body_md: str
    canonical_code: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    note_date: date | None  # None: today (UTC) on create, the stored date on update
    metric_kind: str | None = None  # ratio | capital | quality, with `metric_code`
    metric_code: str | None = None


def label_of(code: str | None) -> str | None:
    """The line's label, or None for a note with no line."""
    return next((i.label for i in canonical_items() if i.code == code), None)


def note_labels(session: Session, notes: list[Note]) -> dict[int, str | None]:
    """The label of each note's subject (its line or metric), by note id; None for a note with
    neither."""
    labels = _metric_labels(session, {n.metric_kind for n in notes if n.metric_kind})
    return {
        n.id: label_of(n.canonical_code)
        if n.metric_kind is None
        else labels[n.metric_kind].get(n.metric_code or "")
        for n in notes
    }


def _metric_labels(session: Session, kinds: set[str]) -> dict[str, dict[str, str]]:
    """Label by code for each wanted metric kind. QoE rules are read only when asked for (custom
    rules are stored, so their labels come from the session)."""
    sources: dict[str, Callable[[], dict[str, str]]] = {
        "ratio": lambda: {r.code: r.label for r in RATIOS},
        "capital": lambda: CAPITAL_METRICS,
        "quality": lambda: {r.code: r.label for r in qoe.effective(session)},
    }
    return {kind: sources[kind]() for kind in kinds}


def list_notes(
    session: Session,
    company: Company,
    code: str | None,
    fiscal_year: int | None,
    fiscal_period: str | None,
    metric_kind: str | None = None,
    metric_code: str | None = None,
) -> list[Note]:
    """Newest `note_date` first. A filter by subject (`code` for a line, or `metric_kind` +
    `metric_code`), by period or by both (see `repositories/notes.py::list_for`); a period is
    `fiscal_year` and `fiscal_period` together. An unknown subject or period matches nothing.
    Raises InvalidNote for only one of the period pair or of the metric pair, a metric kind
    outside `METRIC_KINDS`, or a line and a metric together."""
    _check_period(fiscal_year, fiscal_period)
    _check_subject(code, metric_kind, metric_code)
    period = None if fiscal_year is None or fiscal_period is None else (fiscal_year, fiscal_period)
    metric = None if metric_kind is None or metric_code is None else (metric_kind, metric_code)
    return repo.list_for(session, company.id, code, period, metric)


def link_counts(session: Session, company: Company) -> list[LinkCount]:
    """The distinct links of the company's notes with their counts (drives the grid markers)."""
    return repo.link_counts(session, company.id)


def create_note(session: Session, company: Company, data: NoteInput, now: datetime) -> Note:
    """Validates, stores (body stripped) and commits. Raises InvalidNote for a blank body or one
    over `BODY_LIMIT`, an unknown line code, a metric of an unknown kind or code (ratio codes,
    capital codes, or the QoE rule codes built-in and custom), a line together with a metric, a
    year without a period (or the reverse), or a period the company has no statements for."""
    body = _validate(session, company, data)
    stamp = _naive_utc(now)
    added = repo.add(
        session,
        Note(
            company_id=company.id,
            body_md=body,
            canonical_code=data.canonical_code,
            metric_kind=data.metric_kind,
            metric_code=data.metric_code,
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
    date, under the rules of `create_note` (so a note on a period the company lacks must be
    re-linked or unlinked to be saved). Raises NoteNotFound for an unknown id (or another
    company's)."""
    stored = _stored(session, company, note_id)
    stored.body_md = _validate(session, company, data)
    stored.canonical_code = data.canonical_code
    stored.metric_kind = data.metric_kind
    stored.metric_code = data.metric_code
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


def _validate(session: Session, company: Company, data: NoteInput) -> str:
    body = data.body_md.strip()
    if not body:
        raise InvalidNote("The note must not be blank")
    if len(body) > BODY_LIMIT:
        raise InvalidNote(f"The note must be at most {BODY_LIMIT:,} characters")
    _check_subject(data.canonical_code, data.metric_kind, data.metric_code)
    if data.canonical_code is not None and label_of(data.canonical_code) is None:
        raise InvalidNote(f"Unknown line item {data.canonical_code!r}")
    if data.metric_kind is not None and data.metric_code is not None:
        if data.metric_code not in _metric_labels(session, {data.metric_kind})[data.metric_kind]:
            raise InvalidNote(f"Unknown {data.metric_kind} metric {data.metric_code!r}")
    _check_period(data.fiscal_year, data.fiscal_period)
    if data.fiscal_year is not None and not YEAR_RANGE[0] <= data.fiscal_year <= YEAR_RANGE[1]:
        raise InvalidNote(f"The fiscal year must be between {YEAR_RANGE[0]} and {YEAR_RANGE[1]}")
    if (
        data.fiscal_year is not None
        and data.fiscal_period is not None
        and (data.fiscal_year, data.fiscal_period) not in fiscal_periods(session, company)
    ):
        name = f"FY{data.fiscal_year}"
        if data.fiscal_period != "FY":
            name = f"{data.fiscal_period} {name}"
        raise InvalidNote(f"{name} is not a period of {company.ticker}")
    return body


def _check_subject(code: str | None, metric_kind: str | None, metric_code: str | None) -> None:
    if (metric_kind is None) != (metric_code is None):
        raise InvalidNote("Give the metric kind and the metric code together, or neither")
    if metric_kind is not None and metric_kind not in METRIC_KINDS:
        raise InvalidNote(f"The metric kind must be one of {METRIC_KINDS}")
    if code is not None and metric_kind is not None:
        raise InvalidNote("A note links to a line or to a metric, not both")


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
