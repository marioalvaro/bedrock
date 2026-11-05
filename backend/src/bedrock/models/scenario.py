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

Case = Literal["base", "bull", "bear"]
CASES: tuple[str, ...] = get_args(Case)
RevenueMethod = Literal["growth", "segments", "volume_price"]
REVENUE_METHODS: tuple[str, ...] = get_args(RevenueMethod)
SegmentDimension = Literal["business", "geo"]
SEGMENT_DIMENSIONS: tuple[str, ...] = get_args(SegmentDimension)


class Scenario(Base):
    """A named set of drivers of a company with one revenue build and exactly three cases
    (FR-FCST-04; docs/erd/forecasting.md "Scenarios and cases"). One scenario per company is the
    default."""

    __tablename__ = "scenario"
    __table_args__ = (
        UniqueConstraint("company_id", "name"),
        # one default scenario per company
        Index(
            "uq_scenario_default",
            "company_id",
            unique=True,
            sqlite_where=text("is_default = 1"),
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


class ScenarioCase(Base):
    """One of a scenario's three cases. `base` holds the scenario's own values; `bull` and `bear`
    hold overrides on its `base` (docs/erd/forecasting.md "Scenarios and cases")."""

    __tablename__ = "scenario_case"
    __table_args__ = (
        UniqueConstraint("scenario_id", "case"),
        CheckConstraint("\"case\" IN ('base', 'bull', 'bear')", name="case"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False
    )
    # one of CASES
    case: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class ScenarioYearMode(Base):
    """How a forecast year of the quarterly span is set, for all three cases of a scenario: one
    annual value or quarter by quarter (docs/erd/forecasting.md "Year modes"). No row is
    `annual`."""

    __tablename__ = "scenario_year_mode"
    __table_args__ = (CheckConstraint("mode IN ('annual', 'quarterly')", name="mode"),)

    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenario.id", ondelete="CASCADE"), primary_key=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    # `quarterly` (forecast/grid.py::YearModeValue; an annual year has no row)
    mode: Mapped[str] = mapped_column(String, nullable=False)
