"""Thesis checkpoints (FR-NOTE-03; docs/erd/workspace.md "Thesis checkpoints (M7c)")."""

from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from bedrock.analysis.checkpoints import AtRiskBy, State
from bedrock.models.thesis_checkpoint import CheckpointFreq
from bedrock.services.checkpoints import (
    CheckpointInput,
    CheckpointList,
    CheckpointView,
)

# A margin as sent: a number (a JSON string or number, a fraction) or a constant such as "1%".
MarginIn = str | Decimal | None


class CheckpointIn(BaseModel):
    statement: str
    label: str | None = None
    freq: CheckpointFreq = "ttm"
    margin: MarginIn = None

    def to_input(self) -> CheckpointInput:
        margin = None if self.margin is None else str(self.margin)
        return CheckpointInput(self.statement, self.label, self.freq, margin)


class CheckpointPeriodOut(BaseModel):
    fiscal_year: int
    fiscal_period: str
    label: str


class CheckpointOut(BaseModel):
    """A checkpoint with its state on the latest data. `left`, `right` and `gap` (the room left)
    are at `period`, the last period where both sides have a value; `previous_state` is the
    state as of the day before the newest report (null with no report or with `error`)."""

    id: int
    label: str
    statement: str
    freq: CheckpointFreq
    margin: Decimal | None
    state: State
    previous_state: State | None
    changed: bool
    at_risk_by: AtRiskBy | None
    period: CheckpointPeriodOut | None
    left: Decimal | None
    right: Decimal | None
    gap: Decimal | None
    unit: str | None = Field(
        description="The unit both sides are in (pct, USD, x, …); null when unknown"
    )
    error: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        # SQLite keeps no time zone: without a zone in the JSON a browser reads local time.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_view(cls, view: CheckpointView) -> "CheckpointOut":
        row, evaluation, period = view.row, view.evaluation, view.period
        return cls(
            id=row.id,
            label=row.label,
            statement=row.statement,
            freq=row.freq,
            margin=row.margin,
            state=view.state,
            previous_state=view.previous_state,
            changed=view.changed,
            at_risk_by=view.at_risk_by,
            period=None
            if period is None
            else CheckpointPeriodOut(
                fiscal_year=period.fiscal_year,
                fiscal_period=period.fiscal_period,
                label=period.label,
            ),
            left=evaluation.left,
            right=evaluation.right,
            gap=evaluation.gap,
            unit=view.unit,
            error=view.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class CheckpointReportOut(BaseModel):
    form: str
    filed_at: date


class CheckpointListOut(BaseModel):
    """The newest 10-K or 10-Q (null for a manual company or none stored) and the checkpoints."""

    report: CheckpointReportOut | None
    checkpoints: list[CheckpointOut]

    @classmethod
    def from_list(cls, found: CheckpointList) -> "CheckpointListOut":
        report = found.report
        return cls(
            report=None
            if report is None
            else CheckpointReportOut(form=report.form, filed_at=report.filed_at),
            checkpoints=[CheckpointOut.from_view(v) for v in found.checkpoints],
        )
