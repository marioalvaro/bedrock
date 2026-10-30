from datetime import UTC, date, datetime
from typing import Literal, cast

from pydantic import BaseModel, field_validator

from bedrock.models.note import Note
from bedrock.services.notes import LinkCount, NoteInput

FiscalPeriod = Literal["FY", "Q1", "Q2", "Q3", "Q4"]
MetricKind = Literal["ratio", "capital", "quality"]


class NoteIn(BaseModel):
    """The link is a subject (`canonical_code` for a line, or `metric_kind` + `metric_code` for a
    ratio, capital or quality metric; not both) and/or `fiscal_year` + `fiscal_period` (a cell,
    a subject, a period or none). A PUT replaces the whole note, so leaving the link out unlinks it;
    `note_date` defaults to today (UTC) on a POST and keeps the stored date on a PUT."""

    body_md: str
    canonical_code: str | None = None
    metric_kind: MetricKind | None = None
    metric_code: str | None = None
    fiscal_year: int | None = None
    fiscal_period: FiscalPeriod | None = None
    note_date: date | None = None

    def to_input(self) -> NoteInput:
        return NoteInput(**self.model_dump())


class NoteOut(BaseModel):
    id: int
    body_md: str
    canonical_code: str | None
    metric_kind: MetricKind | None
    metric_code: str | None
    label: str | None  # of the line or the metric
    fiscal_year: int | None
    fiscal_period: str | None
    note_date: date
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        # SQLite keeps no time zone: without a zone in the JSON a browser reads local time.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_model(cls, note: Note, label: str | None) -> "NoteOut":
        return cls(
            id=note.id,
            body_md=note.body_md,
            canonical_code=note.canonical_code,
            metric_kind=cast("MetricKind | None", note.metric_kind),
            metric_code=note.metric_code,
            label=label,
            fiscal_year=note.fiscal_year,
            fiscal_period=note.fiscal_period,
            note_date=note.note_date,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )


class NoteLinkOut(BaseModel):
    """One distinct link and how many notes have it."""

    canonical_code: str | None
    metric_kind: MetricKind | None
    metric_code: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    count: int

    @classmethod
    def from_count(cls, link: LinkCount) -> "NoteLinkOut":
        return cls(**link.__dict__)
