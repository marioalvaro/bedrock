from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_validator

from bedrock.analysis.guidance import Basis, Direction, MetricSummary, Verdict
from bedrock.services.guidance import (
    GuidanceInput,
    GuidanceLog,
    LoggedEntry,
    MetricChoice,
)

FiscalPeriod = Literal["FY", "Q1", "Q2", "Q3", "Q4"]


class GuidanceIn(BaseModel):
    """`low` and `high` are in the metric's units and the displayed sign convention of the
    statements (capex guidance of 10-11 B is -11 B to -10 B); a point estimate has low = high.
    `direction` defaults from the metric."""

    metric: str
    fiscal_year: int
    fiscal_period: FiscalPeriod
    low: Decimal
    high: Decimal
    basis: Basis
    direction: Direction | None = None
    given_on: date
    source_note: str | None = None

    def to_input(self) -> GuidanceInput:
        return GuidanceInput(**self.model_dump())


class MetricChoiceOut(BaseModel):
    metric: str
    label: str
    group: Literal["line", "ratio", "kpi"]
    unit: str
    default_direction: Direction
    quarterly: bool

    @classmethod
    def from_choice(cls, c: MetricChoice) -> "MetricChoiceOut":
        return cls(**c.__dict__)


class GuidanceEntryOut(BaseModel):
    """`unit` is null for a KPI whose series was deleted (the entry stays, pending). `surprise` is
    (actual - midpoint) / |midpoint|, not flipped for `lower`. `latest` is false for a revision."""

    id: int
    metric: str
    label: str
    unit: str | None
    fiscal_year: int
    fiscal_period: str
    low: Decimal
    high: Decimal
    basis: Basis
    direction: Direction
    given_on: date
    source_note: str | None
    actual: Decimal | None
    verdict: Verdict
    surprise: Decimal | None
    latest: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        # SQLite keeps no time zone: without a zone in the JSON a browser reads local time.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_logged(cls, e: LoggedEntry) -> "GuidanceEntryOut":
        g, r = e.stored, e.result
        return cls(
            id=g.id,
            metric=g.metric,
            label=e.label,
            unit=e.unit,
            fiscal_year=g.fiscal_year,
            fiscal_period=g.fiscal_period,
            low=g.low,
            high=g.high,
            basis=r.entry.basis,
            direction=r.entry.direction,
            given_on=g.given_on,
            source_note=g.source_note,
            actual=r.actual,
            verdict=r.verdict,
            surprise=r.surprise,
            latest=r.latest,
            created_at=g.created_at,
            updated_at=g.updated_at,
        )


class GuidanceSummaryOut(BaseModel):
    """Counts of the latest entries; `hit_rate` = (beat + in_range) / (beat + in_range + miss),
    null when nothing is decided."""

    beat: int
    in_range: int
    miss: int
    pending: int
    hit_rate: Decimal | None


class MetricSummaryOut(GuidanceSummaryOut):
    metric: str
    label: str

    @classmethod
    def from_summary(cls, s: MetricSummary, label: str) -> "MetricSummaryOut":
        return cls(**s.__dict__, label=label)


class GuidanceOut(BaseModel):
    ticker: str
    entries: list[GuidanceEntryOut]  # by fiscal year, period (FY first), metric, given_on
    summary: GuidanceSummaryOut
    by_metric: list[MetricSummaryOut]  # by metric code

    @classmethod
    def from_log(cls, ticker: str, log: GuidanceLog) -> "GuidanceOut":
        s = log.summary
        return cls(
            ticker=ticker,
            entries=[GuidanceEntryOut.from_logged(e) for e in log.entries],
            summary=GuidanceSummaryOut(
                beat=s.beat,
                in_range=s.in_range,
                miss=s.miss,
                pending=s.pending,
                hit_rate=s.hit_rate,
            ),
            by_metric=[MetricSummaryOut.from_summary(m, log.labels[m.metric]) for m in s.by_metric],
        )
