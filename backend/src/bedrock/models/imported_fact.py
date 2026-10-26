from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class ImportedFact(Base):
    """One value of an import, for a canonical line or a custom line (`custom:<slug>`). `value` is
    in units and in the reported convention (the displayed value divided by the line's sign). A
    later import of the same (line, period) wins; the earlier one stays as a vintage."""

    __tablename__ = "imported_fact"
    __table_args__ = (
        UniqueConstraint("import_id", "line_code", "fiscal_year", "fiscal_period"),
        CheckConstraint("fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3', 'Q4')", name="fiscal_period"),
        Index(
            "ix_imported_fact_company_line",
            "company_id",
            "line_code",
            "fiscal_year",
            "fiscal_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("statement_import.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    line_code: Mapped[str] = mapped_column(String, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String, nullable=False)
    # NULL for an instant (a balance-sheet line)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
