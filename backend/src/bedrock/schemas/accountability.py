from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bedrock.analysis.guidance import Basis, Verdict
from bedrock.analysis.qoe import RuleUnit, Severity
from bedrock.models.audit_log import AuditAction, AuditEntity
from bedrock.schemas.checkpoints import CheckpointOut
from bedrock.services.audit import AuditPage
from bedrock.services.backtest import BacktestView
from bedrock.services.guidance import LoggedEntry
from bedrock.services.review import EarningsReview, ReviewLine
from bedrock.services.snapshots import SnapshotDetail, SnapshotList, SnapshotView


class SnapshotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = None


class ScoreRowOut(BaseModel):
    """Errors of one line or driver at one horizon. `method` is the case of a snapshot and the
    engine of a backtest; `hit_rate` is null when no row of the group has a range."""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["line", "driver"]
    code: str
    label: str
    unit: str
    method: str
    freq: Literal["annual", "quarterly"]
    horizon: int
    n: int
    mape: Decimal | None
    bias: Decimal | None
    hit_rate: Decimal | None
    n_range: int


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scenario_id: int | None
    scenario_name: str
    note: str | None
    created_at: datetime
    data_as_of: date | None
    failed_cases: list[str]
    scored_periods: int
    revenue_mape: Decimal | None
    # M7d S4: the company's classification mode when it was taken; null for an older snapshot
    classification_mode: Literal["off", "accepted", "all"] | None
    # M7c: `auto` when a refresh took it just before storing a new 10-K or 10-Q
    origin: Literal["manual", "auto"]

    @classmethod
    def from_view(cls, view: SnapshotView) -> "SnapshotOut":
        return cls.model_validate(view)


class SnapshotListOut(BaseModel):
    snapshots: list[SnapshotOut]
    summary: list[ScoreRowOut]

    @classmethod
    def from_view(cls, view: SnapshotList) -> "SnapshotListOut":
        return cls(
            snapshots=[SnapshotOut.from_view(s) for s in view.snapshots],
            summary=[ScoreRowOut.model_validate(r) for r in view.summary],
        )


class SnapshotLineCellOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fiscal_year: int
    fiscal_period: str
    label: str
    horizon: int
    forecast: Decimal
    actual: Decimal | None
    pct_error: Decimal | None
    in_range: bool | None


class SnapshotDriverCellOut(SnapshotLineCellOut):
    source: str | None
    p05: Decimal | None
    p95: Decimal | None


class SnapshotLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    unit: str
    cells: list[SnapshotLineCellOut]


class SnapshotDriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    unit: str
    cells: list[SnapshotDriverCellOut]


class SnapshotValuationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    value_per_share: Decimal | None
    equity_value: Decimal | None
    enterprise_value: Decimal | None
    upside: Decimal | None
    error: str | None


class SnapshotCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case: Literal["base", "bull", "bear"]
    error: str | None
    warnings: list[str]
    lines: list[SnapshotLineOut]
    drivers: list[SnapshotDriverOut]
    valuation: list[SnapshotValuationOut]


class SnapshotDetailOut(SnapshotOut):
    cases: list[SnapshotCaseOut]

    @classmethod
    def from_detail(cls, view: SnapshotDetail) -> "SnapshotDetailOut":
        return cls.model_validate(view)


class BacktestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    method: str
    error: str | None


class BacktestOriginOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    runs: list[BacktestRunOut]


class BacktestOut(BaseModel):
    """`ran_at` is null and the lists are empty before the first run; `stale`: a newer 10-K exists
    than the run's origins imply."""

    model_config = ConfigDict(from_attributes=True)

    ran_at: datetime | None
    stale: bool
    origins: list[BacktestOriginOut]
    summary: list[ScoreRowOut]

    @classmethod
    def from_view(cls, view: BacktestView) -> "BacktestOut":
        return cls.model_validate(view)


class AuditRowOut(BaseModel):
    """One changed field. A null `old_value` or `new_value` means absent (a driver or input with
    no stored value of its own)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    entity: AuditEntity
    scope: str | None
    field: str
    label: str
    unit: str | None
    old_value: str | None
    new_value: str | None
    action: AuditAction
    rationale: str | None
    changed_at: datetime


class AuditPageOut(BaseModel):
    rows: list[AuditRowOut]
    next_before_id: int | None

    @classmethod
    def from_view(cls, view: AuditPage) -> "AuditPageOut":
        return cls(
            rows=[AuditRowOut.model_validate(r) for r in view.rows],
            next_before_id=view.next_before_id,
        )


class AuditRationaleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str | None  # blank or null clears it


# --- earnings review (M7c, FR-ACC-06) ------------------------------------------------------------


class ReviewFilingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accession_no: str
    form: str
    filed_at: date
    period_end: date


class ReviewPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fiscal_year: int
    fiscal_period: str
    label: str


class ReviewSnapshotOut(BaseModel):
    """The snapshot taken on data older than the filing; `classification_mode` is the snapshot's
    own (the actuals are read under the company's current mode)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scenario_name: str
    origin: Literal["manual", "auto"]
    created_at: datetime
    data_as_of: date | None
    classification_mode: Literal["off", "accepted", "all"] | None


class RangeOut(BaseModel):
    """A latest guidance or consensus entry on the line at the period. `actual` is the entry's own
    (judged on its basis), so it can differ from the line's."""

    low: Decimal
    high: Decimal
    basis: Basis
    actual: Decimal | None
    verdict: Verdict
    surprise: Decimal | None
    given_on: date

    @classmethod
    def from_entry(cls, logged: LoggedEntry | None) -> "RangeOut | None":
        if logged is None:
            return None
        result = logged.result
        entry = result.entry
        return cls(
            low=entry.low,
            high=entry.high,
            basis=entry.basis,
            actual=result.actual,
            verdict=result.verdict,
            surprise=result.surprise,
            given_on=entry.given_on,
        )


class ReviewLineOut(BaseModel):
    code: str
    label: str
    unit: str
    actual: Decimal | None
    prior_year: Decimal | None
    yoy: Decimal | None
    forecast: Decimal | None  # the snapshot's Base
    low: Decimal | None  # the Bull-Bear envelope; null unless all three cases have a forecast
    high: Decimal | None
    pct_error: Decimal | None
    in_range: bool | None
    consensus: RangeOut | None
    guidance: RangeOut | None

    @classmethod
    def from_line(cls, line: ReviewLine) -> "ReviewLineOut":
        pick = line.snapshot
        return cls(
            code=line.code,
            label=line.label,
            unit=line.unit,
            actual=line.actual,
            prior_year=line.prior_year,
            yoy=line.yoy,
            forecast=pick.forecast,
            low=pick.low,
            high=pick.high,
            pct_error=pick.pct_error,
            in_range=pick.in_range,
            consensus=RangeOut.from_entry(line.consensus),
            guidance=RangeOut.from_entry(line.guidance),
        )


class ReviewDriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    unit: str
    forecast: Decimal
    actual: Decimal | None
    pct_error: Decimal
    in_range: bool | None
    source: str | None


class RestatedOut(BaseModel):
    """A prior value the filing changed: the read the day before it against the read now."""

    model_config = ConfigDict(from_attributes=True)

    statement: Literal["IS", "BS", "CF"]
    code: str
    label: str
    unit: str
    fiscal_year: int
    fiscal_period: str
    before: Decimal
    after: Decimal
    pct_change: Decimal | None  # null when before is 0


class FlagChangeOut(BaseModel):
    """A QoE flag whose severity at the last period changed with the filing (null: no value)."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    unit: RuleUnit
    before: Severity | None
    after: Severity | None
    value_before: Decimal | None
    value_after: Decimal | None


class EarningsReviewOut(BaseModel):
    """The review of the newest 10-K or 10-Q; `filing` null (none stored) leaves every list
    empty. `restated` holds the first 50 of `restated_total`."""

    ticker: str
    filing: ReviewFilingOut | None
    period: ReviewPeriodOut | None
    snapshot: ReviewSnapshotOut | None
    lines: list[ReviewLineOut]
    drivers: list[ReviewDriverOut]
    drivers_note: str | None
    restated: list[RestatedOut]
    restated_total: int
    flags: list[FlagChangeOut]
    checkpoints: list[CheckpointOut]

    @classmethod
    def from_review(cls, review: EarningsReview) -> "EarningsReviewOut":
        return cls(
            ticker=review.ticker,
            filing=None if review.filing is None else ReviewFilingOut.model_validate(review.filing),
            period=None if review.period is None else ReviewPeriodOut.model_validate(review.period),
            snapshot=None
            if review.snapshot is None
            else ReviewSnapshotOut.model_validate(review.snapshot),
            lines=[ReviewLineOut.from_line(line) for line in review.lines],
            drivers=[ReviewDriverOut.model_validate(d) for d in review.drivers],
            drivers_note=review.drivers_note,
            restated=[RestatedOut.model_validate(r) for r in review.restated],
            restated_total=review.restated_total,
            flags=[FlagChangeOut.model_validate(f) for f in review.flags],
            checkpoints=[CheckpointOut.from_view(c) for c in review.checkpoints],
        )
