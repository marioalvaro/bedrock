from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base


class ValuationInput(Base):
    """One valuation input a scenario case sets itself (docs/erd/valuation.md "Tables", "Inputs").
    A missing row inherits (Bull and Bear: Base's, then the default). `value` is the input as
    text, never a float (G15, G21)."""

    __tablename__ = "valuation_input"
    __table_args__ = (UniqueConstraint("case_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_case.id", ondelete="CASCADE"), nullable=False
    )
    # a `valuation/inputs.py` catalog code
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
