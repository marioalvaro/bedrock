from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import (
    Boolean,
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

RevenueMethod = Literal["growth", "segments", "volume_price"]
REVENUE_METHODS: tuple[str, ...] = get_args(RevenueMethod)
SegmentDimension = Literal["business", "geo"]
SEGMENT_DIMENSIONS: tuple[str, ...] = get_args(SegmentDimension)


class Scenario(Base):
    """A named driver set of a company (FR-FCST-04). Base (`is_default`, no `base_id`) is the one
    every other scenario of the company overrides (docs/erd/forecasting.md "Scenarios")."""

    __tablename__ = "scenario"
    __table_args__ = (
        UniqueConstraint("company_id", "name"),
        # one Base per company
        Index(
            "uq_scenario_default",
            "company_id",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
        CheckConstraint(
            "(is_default = 1 AND base_id IS NULL) OR (is_default = 0 AND base_id IS NOT NULL)",
            name="base",
        ),
        CheckConstraint(
            "revenue_method IN ('growth', 'segments', 'volume_price')", name="revenue_method"
        ),
        CheckConstraint("segment_dimension IN ('business', 'geo')", name="segment_dimension"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenario.id", ondelete="CASCADE"), nullable=True
    )
    # one of REVENUE_METHODS
    revenue_method: Mapped[str] = mapped_column(String, nullable=False, default="growth")
    # one of SEGMENT_DIMENSIONS; required for `segments`
    segment_dimension: Mapped[str | None] = mapped_column(String, nullable=True)
    # KPI codes (segment_series.metric of a `kpi` series); required for `volume_price`
    volume_kpi: Mapped[str | None] = mapped_column(String, nullable=True)
    price_kpi: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
