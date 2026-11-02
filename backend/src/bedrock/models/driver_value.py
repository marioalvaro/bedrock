from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base

DriverKind = Literal["value", "offset"]
DRIVER_KINDS: tuple[str, ...] = get_args(DriverKind)


class DriverValue(Base):
    """One stored driver of a scenario case for a fiscal year or one of its quarters: a `value`,
    or an `offset` on its scenario's `base` case (docs/erd/forecasting.md "Scenarios and cases").
    `pct` drivers are fractions."""

    __tablename__ = "driver_value"
    __table_args__ = (
        UniqueConstraint("case_id", "driver_code", "fiscal_year", "fiscal_period"),
        CheckConstraint("fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3', 'Q4')", name="fiscal_period"),
        CheckConstraint("kind IN ('value', 'offset')", name="kind"),
        CheckConstraint("source IN ('manual', 'engine')", name="source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_case.id", ondelete="CASCADE"), nullable=False
    )
    # a `forecast/drivers.py` code; `segment_growth:<series id>` for a segment
    driver_code: Mapped[str] = mapped_column(String, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # FY for a year's driver, Q1..Q4 for a quarter of the quarterly span (M4 S7)
    fiscal_period: Mapped[str] = mapped_column(String, nullable=False, default="FY")
    # one of DRIVER_KINDS
    kind: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    # manual | engine (M6)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    engine_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
