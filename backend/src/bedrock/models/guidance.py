from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base


class Guidance(Base):
    """One guidance entry of the company (FR-ANL-09): a range for a metric in a fiscal period."""

    __tablename__ = "guidance"
    __table_args__ = (
        CheckConstraint("low <= high", name="low_le_high"),
        CheckConstraint("fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3', 'Q4')", name="fiscal_period"),
        CheckConstraint("basis IN ('reported', 'normalized')", name="basis"),
        CheckConstraint("direction IN ('higher', 'lower')", name="direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # a canonical code, a ratio code or `kpi:<code>`
    metric: Mapped[str] = mapped_column(String, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String, nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    basis: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    given_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
