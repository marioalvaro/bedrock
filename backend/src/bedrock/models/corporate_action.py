from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class CorporateAction(Base):
    __tablename__ = "corporate_action"
    __table_args__ = (UniqueConstraint("company_id", "effective_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)  # split / reverse_split
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    # New shares per old share: 4 for a 4-for-1 split, 0.1 for a 1-for-10 reverse split.
    ratio: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
