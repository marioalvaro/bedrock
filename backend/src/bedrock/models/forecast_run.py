from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base

SnapshotOrigin = Literal["manual", "auto"]  # `auto`: taken by a refresh before a new report


class ForecastSnapshot(Base):
    """A frozen copy of a scenario (FR-ACC-01; docs/erd/accountability.md "Snapshots"). Nothing
    updates or deletes one except the company's cascade; the scenario may go first, so its name is
    kept as text."""

    __tablename__ = "forecast_snapshot"
    __table_args__ = (
        Index("ix_forecast_snapshot_company_created", "company_id", "created_at"),
        CheckConstraint("origin IN ('manual', 'auto')", name="origin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenario.id", ondelete="SET NULL"), nullable=True
    )
    scenario_name: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # the newest filing the forecast saw; null for a manual company
    data_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # M7d: the company's classification mode when the snapshot was taken; null before 0022
    classification_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    # M7c: `auto` when the refresh took it before storing a new report, whose accession it keeps
    origin: Mapped[SnapshotOrigin] = mapped_column(
        String, nullable=False, default="manual", server_default="manual"
    )
    trigger_accession: Mapped[str | None] = mapped_column(String, nullable=True)


class ForecastRun(Base):
    """A stored forecast (docs/erd/forecasting.md "Tables"): one case of a snapshot, or one method
    from one origin of a backtest. `error` means it could not run and has no values."""

    __tablename__ = "forecast_run"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "case"),
        UniqueConstraint("company_id", "as_of_date", "method"),
        CheckConstraint("kind IN ('snapshot', 'backtest')", name="kind"),
        CheckConstraint("\"case\" IN ('base', 'bull', 'bear')", name="case"),
        CheckConstraint(
            "(kind = 'snapshot' AND snapshot_id IS NOT NULL AND \"case\" IS NOT NULL) "
            "OR (kind = 'backtest' AND method IS NOT NULL)",
            name="kind_columns",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("forecast_snapshot.id", ondelete="CASCADE"), nullable=True
    )
    case: Mapped[str | None] = mapped_column(String(4), nullable=True)  # a snapshot run's
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)  # a backtest run's
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    engines_json: Mapped[str] = mapped_column(Text, nullable=False)  # `backtest/snapshot.run_meta`
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ForecastValue(Base):
    """One stored line or driver value of a run (docs/erd/accountability.md "Stored rows")."""

    __tablename__ = "forecast_value"
    __table_args__ = (CheckConstraint("kind IN ('line', 'driver')", name="kind"),)

    forecast_run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_run.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(6), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_period: Mapped[str] = mapped_column(String(2), primary_key=True)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    point: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    p05: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    p25: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    p50: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    p75: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    p95: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    source: Mapped[str | None] = mapped_column(String(10), nullable=True)


class ValuationRun(Base):
    """A snapshot's frozen valuation: one per case and `ValuationResult` (docs/erd/valuation.md
    "Tables"). A method that could not value has `error` and null numbers."""

    __tablename__ = "valuation_run"
    __table_args__ = (UniqueConstraint("forecast_run_id", "method_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    forecast_run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_run.id", ondelete="CASCADE"), nullable=False
    )
    method_code: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    value_per_share: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    equity_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    enterprise_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    upside: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
