from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class Filing(Base):
    __tablename__ = "filing"
    __table_args__ = (Index("ix_filing_company_id", "company_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    accession_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    form: Mapped[str] = mapped_column(String, nullable=False)
    filed_at: Mapped[date] = mapped_column(Date, nullable=False)
    # EDGAR's fy/fp as given: they describe the filing, not the period.
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # M7b S6: NULL = not tried, `parsed`, `absent` (the folder has no XBRL instance), `failed`.
    xbrl_status: Mapped[str | None] = mapped_column(
        String,
        CheckConstraint(
            "xbrl_status IN ('parsed', 'absent', 'failed')", name="ck_filing_xbrl_status"
        ),
        nullable=True,
    )
    xbrl_parser_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
