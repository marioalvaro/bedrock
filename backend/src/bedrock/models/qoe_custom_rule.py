from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base


class QoeCustomRule(Base):
    """A user-defined quality-of-earnings rule (FR-ANL-10), global. Its code is `custom_<id>`.
    `formula` and the `*_formula` levels hold the text as the user typed it (stripped); each level
    is a number or a formula, never both."""

    __tablename__ = "qoe_custom_rule"
    __table_args__ = (
        CheckConstraint("direction IN ('above', 'below')", name="direction"),
        CheckConstraint("unit IN ('pct', 'x')", name="unit"),
        CheckConstraint("warn IS NULL OR warn_formula IS NULL", name="warn_number_or_formula"),
        CheckConstraint("alert IS NULL OR alert_formula IS NULL", name="alert_number_or_formula"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    formula: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    warn: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    alert: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    warn_formula: Mapped[str | None] = mapped_column(String, nullable=True)
    alert_formula: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
