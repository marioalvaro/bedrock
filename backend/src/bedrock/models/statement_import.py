from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class StatementImport(Base):
    """One confirmed upload of statement values (FR-DATA-15); its facts go with it."""

    __tablename__ = "statement_import"
    __table_args__ = (
        CheckConstraint("format IN ('xlsx', 'csv')", name="format"),
        CheckConstraint("scale IN ('units', 'thousands', 'millions', 'billions')", name="scale"),
        Index("ix_statement_import_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    # xlsx | csv
    format: Mapped[str] = mapped_column(String, nullable=False)
    # units | thousands | millions | billions: how the file's USD and share values were typed
    scale: Mapped[str] = mapped_column(String, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cells: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
