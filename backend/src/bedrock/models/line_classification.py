from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class LineClassification(Base):
    """One answer of one classifier for one face line of one company (M7d S3,
    docs/erd/face-tree.md "Storage"). `classifier` is a registry name or `user`. `codes` is a
    JSON list of canonical codes: `[]` none of the rows, one code that row, several one combined
    line. A proposal until the user decides; at most one row of a line is `accepted`."""

    __tablename__ = "line_classification"
    __table_args__ = (
        UniqueConstraint("company_id", "statement", "taxonomy", "concept", "classifier"),
        CheckConstraint("statement IN ('IS', 'BS', 'CF')", name="statement"),
        CheckConstraint("status IN ('proposed', 'accepted', 'rejected')", name="status"),
        Index("ix_line_classification_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    statement: Mapped[str] = mapped_column(String, nullable=False)
    taxonomy: Mapped[str] = mapped_column(String, nullable=False)
    concept: Mapped[str] = mapped_column(String, nullable=False)
    classifier: Mapped[str] = mapped_column(String, nullable=False)
    codes: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_run.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
