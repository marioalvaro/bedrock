import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class MacroSeries(Base):
    """A market or macro series: the risk-free rate (FRED `DGS10`, or yfinance `^TNX`), the
    Damodaran implied ERP (`DAMODARAN_ERP`) and the S&P 500 monthly closes (`^GSPC`)."""

    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # UTC without a time zone (SQLite keeps none).
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)


class MacroObservation(Base):
    __tablename__ = "macro_observation"

    series_id: Mapped[str] = mapped_column(
        ForeignKey("macro_series.series_id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    # As published: a percentage for rates and the ERP, index points for an index.
    value: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
