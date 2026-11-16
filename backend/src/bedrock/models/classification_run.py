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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class ClassificationRun(Base):
    """One click on "Classify lines" (M7d S3, docs/erd/face-tree.md "Storage"): a classifier
    asked about a company's open lines. At most one row in the whole database is `running`.
    `error` is the reason of a `failed` or `stopped` run."""

    __tablename__ = "classification_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'done', 'failed', 'stopped')", name="status"),
        Index("ix_classification_run_company_id", "company_id"),
        # the budgets sum the runs started in a UTC day and month
        Index("ix_classification_run_started_at", "started_at"),
        Index(
            "uq_classification_run_running",
            "status",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    classifier: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lines_asked: Mapped[int] = mapped_column(Integer, nullable=False)
    lines_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
