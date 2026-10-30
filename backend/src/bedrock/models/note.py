from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base


class Note(Base):
    """A Markdown note (FR-NOTE-01/02), optionally linked to a subject (a canonical line, or a
    ratio / capital / quality metric) and a fiscal period."""

    __tablename__ = "note"
    __table_args__ = (
        CheckConstraint(
            "(fiscal_year IS NULL) = (fiscal_period IS NULL)", name="period_both_or_none"
        ),
        CheckConstraint(
            "fiscal_period IS NULL OR fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3', 'Q4')",
            name="fiscal_period",
        ),
        CheckConstraint(
            "(metric_kind IS NULL) = (metric_code IS NULL)", name="metric_both_or_none"
        ),
        CheckConstraint(
            "metric_kind IS NULL OR metric_kind IN ('ratio', 'capital', 'quality')",
            name="metric_kind",
        ),
        CheckConstraint("canonical_code IS NULL OR metric_kind IS NULL", name="line_or_metric"),
        Index("ix_note_company_metric", "company_id", "metric_kind", "metric_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body_md: Mapped[str] = mapped_column(String, nullable=False)
    canonical_code: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_code: Mapped[str | None] = mapped_column(String, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String, nullable=True)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
