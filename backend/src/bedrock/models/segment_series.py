from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base

Dimension = Literal["business", "geo", "kpi"]
DIMENSIONS: tuple[str, ...] = get_args(Dimension)
SegmentUnit = Literal["USD", "pct", "count", "USD_per_unit"]
UNITS: tuple[str, ...] = get_args(SegmentUnit)


class SegmentSeries(Base):
    """One manually entered series (FR-DATA-11): a business or geographic segment's revenue or
    operating income, or a KPI (whose `metric` is its code)."""

    __tablename__ = "segment_series"
    __table_args__ = (
        UniqueConstraint("company_id", "dimension", "name", "metric"),
        CheckConstraint("dimension IN ('business', 'geo', 'kpi')", name="dimension"),
        # a KPI code is unique among the company's KPIs (the service checks it too, for the message)
        Index(
            "uq_segment_series_kpi_code",
            "company_id",
            "metric",
            unique=True,
            sqlite_where=text("dimension = 'kpi'"),
        ),
        CheckConstraint("unit IN ('USD', 'pct', 'count', 'USD_per_unit')", name="unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    # one of DIMENSIONS
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # revenue | operating_income for business/geo; the KPI code for kpi
    metric: Mapped[str] = mapped_column(String, nullable=False)
    # one of UNITS
    unit: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
