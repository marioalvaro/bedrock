from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base


class QoeThreshold(Base):
    """The user's override of one quality-of-earnings rule's thresholds (global). Each level is a
    number or a formula (FR-ANL-10, the text as typed), never both."""

    __tablename__ = "qoe_threshold"
    __table_args__ = (
        CheckConstraint("warn IS NULL OR warn_formula IS NULL", name="warn_number_or_formula"),
        CheckConstraint("alert IS NULL OR alert_formula IS NULL", name="alert_number_or_formula"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    warn: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    alert: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    warn_formula: Mapped[str | None] = mapped_column(String, nullable=True)
    alert_formula: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
