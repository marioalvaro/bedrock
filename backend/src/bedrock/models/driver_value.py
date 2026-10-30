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
    """One stored driver of a scenario for a fiscal year: a `value`, or an `offset` on Base's
    resolved value (docs/erd/forecasting.md "Scenarios"). `pct` drivers are fractions."""

    __tablename__ = "driver_value"
    __table_args__ = (
        UniqueConstraint("scenario_id", "driver_code", "fiscal_year", "fiscal_period"),
        CheckConstraint("fiscal_period = 'FY'", name="fiscal_period"),
        CheckConstraint("kind IN ('value', 'offset')", name="kind"),
        CheckConstraint("source IN ('manual', 'engine')", name="source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False
    )
    # a `forecast/drivers.py` code; `segment_growth:<series id>` for a segment
    driver_code: Mapped[str] = mapped_column(String, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # FY only in M4: drivers are annual
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
