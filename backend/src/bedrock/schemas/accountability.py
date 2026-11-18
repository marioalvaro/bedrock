from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bedrock.models.audit_log import AuditAction, AuditEntity
from bedrock.services.audit import AuditPage
from bedrock.services.backtest import BacktestView
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
