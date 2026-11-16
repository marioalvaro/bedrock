from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class FilingLine(Base):
    """One line on the face of one statement of one filing, with its calculation parent in that
    statement's role (M7b S6). Append-only like `raw_fact`; only `backfill-filings --reparse`
    rebuilds a filing's lines."""

    __tablename__ = "filing_line"
    __table_args__ = (
        UniqueConstraint("filing_id", "statement", "taxonomy", "concept"),
        CheckConstraint("statement IN ('IS', 'BS', 'CF')", name="ck_filing_line_statement"),
        Index("ix_filing_line_filing_id", "filing_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    statement: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # from 1, presentation order
    taxonomy: Mapped[str] = mapped_column(String, nullable=False)
    concept: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    calc_parent_taxonomy: Mapped[str | None] = mapped_column(String, nullable=True)
    calc_parent_concept: Mapped[str | None] = mapped_column(String, nullable=True)
    calc_weight: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
