from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class PendingFiling(Base):
    """A 10-K or 10-Q that EDGAR's filing index lists and `filing` does not hold yet (M7c,
    docs/erd/data.md "New-filing detection"). Rows are deleted, never updated."""

    __tablename__ = "pending_filing"
    __table_args__ = (
        CheckConstraint("form IN ('10-K', '10-Q')", name="form"),
        Index("ix_pending_filing_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    accession_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    form: Mapped[str] = mapped_column(String, nullable=False)
    filed_at: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # naive UTC, when the check first saw it
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
