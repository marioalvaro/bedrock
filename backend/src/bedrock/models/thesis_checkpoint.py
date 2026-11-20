from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base

CheckpointFreq = Literal["annual", "ttm"]


class ThesisCheckpoint(Base):
    """A testable statement of a company's thesis (M7c, FR-NOTE-03; docs/erd/workspace.md "Thesis
    checkpoints"). `statement` is the text as typed (stripped); its state is computed on read,
    never stored. Not audited."""

    __tablename__ = "thesis_checkpoint"
    __table_args__ = (
        CheckConstraint("freq IN ('annual', 'ttm')", name="freq"),
        CheckConstraint("margin IS NULL OR margin >= 0", name="margin"),
        Index("ix_thesis_checkpoint_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    statement: Mapped[str] = mapped_column(String, nullable=False)
    freq: Mapped[CheckpointFreq] = mapped_column(String, nullable=False)
    margin: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
