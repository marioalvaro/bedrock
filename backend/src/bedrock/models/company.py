from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class Company(Base):
    __tablename__ = "company"
    __table_args__ = (CheckConstraint("source IN ('sec', 'manual')", name="source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # NULL only for a manual company (no SEC filer); NULLs do not collide in a unique column.
    cik: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    # sec | manual: where the statements come from (a manual company is filled by import only)
    source: Mapped[str] = mapped_column(String, nullable=False, default="sec", server_default="sec")
    sic: Mapped[str | None] = mapped_column(String, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
