import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class PriceDaily(Base):
    __tablename__ = "price_daily"

    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    adj_close: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
