from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class RawFact(Base):
    """As-reported XBRL fact. Append-only: every filing vintage is kept."""

    __tablename__ = "raw_fact"
    __table_args__ = (
        # SQLite treats NULLs as distinct, so this does not stop duplicate instant facts
        # (period_start NULL); the parser and the repository dedupe those.
        UniqueConstraint("filing_id", "taxonomy", "concept", "unit", "period_start", "period_end"),
        Index("ix_raw_fact_company_concept", "company_id", "taxonomy", "concept"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    filing_id: Mapped[int] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    taxonomy: Mapped[str] = mapped_column(String, nullable=False)
    concept: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # The filing's fy/fp, not the period's.
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String, nullable=True)
    frame: Mapped[str | None] = mapped_column(String, nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
