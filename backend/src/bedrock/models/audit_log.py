from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base

AuditEntity = Literal[
    "driver",
    "year_mode",
    "engine_choice",
    "valuation_input",
    "scenario",
    "adjustment",
    "line_classification",  # M7d: a decision on a classifier's answer, or the user's own
    "company",  # M7d: the company's classification mode
]
AuditAction = Literal["create", "edit", "delete", "import", "reset", "mode"]


class AuditLog(Base):
    """One changed field of an audited write (FR-ACC-04; docs/erd/accountability.md "Audit trail").
    Append-only: `rationale` is the one column ever updated. `entity_id` has no foreign key and the
    label and scope are text, so a row outlives what it describes. A null value means absent."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_company_id_id", "company_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    entity: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    field: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    rationale: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
