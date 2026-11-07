import datetime as dt
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class ConsensusEstimate(Base):
    """Yahoo's analyst consensus for one relative period (0q, +1q, 0y, +1y) and metric (revenue,
    eps), as fetched; placed on fiscal periods when read (analysis/consensus.py)."""

    __tablename__ = "consensus_estimate"

    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), primary_key=True
    )
    period: Mapped[str] = mapped_column(String(4), primary_key=True)
    metric: Mapped[str] = mapped_column(String(10), primary_key=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    avg: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    analysts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_ago_revenue: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    # UTC without a time zone (SQLite keeps none).
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
