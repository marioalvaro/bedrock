from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class Filing(Base):
    __tablename__ = "filing"

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
