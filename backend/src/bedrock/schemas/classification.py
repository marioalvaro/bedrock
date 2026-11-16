"""Payloads of the classification routes (M7d S3, docs/erd/face-tree.md "Routes")."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from bedrock.models.classification_run import ClassificationRun
from bedrock.models.line_classification import LineClassification
from bedrock.repositories import classifications as repo
from bedrock.repositories.numeric import plain
from bedrock.schemas.statements import RowRefOut
from bedrock.services.classification import Overview, Status

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Statement = Literal["IS", "BS", "CF"]
ClassificationStatus = Literal["proposed", "accepted", "rejected"]
ClassificationMode = Literal["off", "accepted", "all"]


class RunIn(BaseModel):
    classifier: Name
    confirm_lines: int = Field(ge=0, description="The number of lines the user confirmed")


class DecisionIn(BaseModel):
    status: ClassificationStatus


class AnswerIn(BaseModel):
    """The user's own answer: `codes` are candidates of the line, empty for none of the rows."""

    statement: Statement
    taxonomy: Name
    concept: Name
    codes: list[str]


class ModeIn(BaseModel):
    mode: ClassificationMode
    source: str | None = Field(description="The classifier whose proposals mode `all` uses")


class ClassifierOut(BaseModel):
    name: str
    configured: bool = Field(description="Its API key is set")


class ClassificationStatusOut(BaseModel):
    classifiers: list[ClassifierOut]
    daily_tokens: int
    monthly_tokens: int
    used_today: int = Field(description="Input + output tokens of the runs of this UTC day")
    used_month: int
    cost_month_usd: Decimal = Field(description="An estimate from the recorded prices")
    max_lines_per_run: int
    min_confidence: float

    @classmethod
    def from_status(cls, status: Status) -> "ClassificationStatusOut":
        return cls(
            classifiers=[ClassifierOut(name=n, configured=c) for n, c in status.classifiers],
            daily_tokens=status.daily_tokens,
            monthly_tokens=status.monthly_tokens,
            used_today=status.used_today,
            used_month=status.used_month,
            cost_month_usd=plain(status.cost_month_usd),
            max_lines_per_run=status.max_lines_per_run,
            min_confidence=status.min_confidence,
        )


class ClassificationRunOut(BaseModel):
    """One click. `error` is the reason of a `failed` or `stopped` run."""

    id: int
    classifier: str
    status: Literal["running", "done", "failed", "stopped"]
    started_at: datetime
    finished_at: datetime | None
    lines_asked: int
    lines_answered: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    error: str | None

    @field_validator("started_at", "finished_at")
    @classmethod
    def _is_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite keeps no time zone: the stored UTC time comes back naive.
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_model(cls, run: ClassificationRun) -> "ClassificationRunOut":
        return cls(
            id=run.id,
            classifier=run.classifier,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            lines_asked=run.lines_asked,
            lines_answered=run.lines_answered,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=plain(run.cost_usd),
            error=run.error,
        )


class ClassificationOut(BaseModel):
    """One answer of one classifier (or of `user`) for a line. `codes`: empty for none of the
    rows, one code for that row, several for one combined line."""

    id: int
    classifier: str
    codes: list[str]
    confidence: Decimal
    status: ClassificationStatus

    @classmethod
    def from_model(cls, row: LineClassification) -> "ClassificationOut":
        return cls(
            id=row.id,
            classifier=row.classifier,
            codes=list(repo.codes_of(row)),
            confidence=plain(row.confidence),
            status=row.status,
        )


class EstimateOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class ClassifiedLineOut(BaseModel):
    statement: Statement
    taxonomy: str
    concept: str
    label: str
    latest_value: Decimal | None
    latest_period_end: date
    block: RowRefOut | None
    candidates: list[RowRefOut]
    effective: list[str] | None = Field(
        description="The codes in force under the company's mode; null when none"
    )
    answers: list[ClassificationOut]


class ClassificationsOut(BaseModel):
    """The company's open lines, in statement then presentation order, with every answer.
    `to_ask` and `estimate` are for the `classifier` parameter; null without it."""

    mode: ClassificationMode
    source: str | None
    run: ClassificationRunOut | None = Field(description="The company's newest run")
    to_ask: int | None = Field(description="Lines a run of the classifier would ask now")
    estimate: EstimateOut | None
    lines: list[ClassifiedLineOut]

    @classmethod
    def from_view(cls, view: Overview) -> "ClassificationsOut":
        def ref(code: str) -> RowRefOut:
            return RowRefOut(code=code, label=view.labels.get(code, code))

        estimate = None
        if view.estimate is not None and view.estimate_cost_usd is not None:
            estimate = EstimateOut(
                input_tokens=view.estimate.input_tokens,
                output_tokens=view.estimate.output_tokens,
                cost_usd=plain(view.estimate_cost_usd),
            )
        return cls(
            mode=view.mode,
            source=view.source,
            run=None if view.run is None else ClassificationRunOut.from_model(view.run),
            to_ask=view.to_ask,
            estimate=estimate,
            lines=[
                ClassifiedLineOut(
                    statement=line.asked.question.statement,
                    taxonomy=line.asked.question.taxonomy,
                    concept=line.asked.question.concept,
                    label=line.asked.question.label,
                    latest_value=line.asked.question.value,
                    latest_period_end=line.asked.question.period_end,
                    block=None
                    if line.asked.line.block_code is None
                    else ref(line.asked.line.block_code),
                    candidates=[
                        RowRefOut(code=c.code, label=c.label)
                        for c in line.asked.question.candidates
                    ],
                    effective=None if line.effective is None else list(line.effective),
                    answers=[ClassificationOut.from_model(row) for row in line.answers],
                )
                for line in view.lines
            ],
        )
