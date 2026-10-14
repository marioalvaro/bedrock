from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


def utc_now() -> datetime:
    # SQLite keeps no time zone, so the columns hold UTC without one.
    return datetime.now(UTC).replace(tzinfo=None)


class Adjustment(Base):
    __tablename__ = "adjustment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    canonical_code: Mapped[str] = mapped_column(String, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String, nullable=False)
    # USD units, in the displayed sign convention.
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    category: Mapped[str] = mapped_column(
        String, nullable=False
    )  # one-off/restatement/reclass/other
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
