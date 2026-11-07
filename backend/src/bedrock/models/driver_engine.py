from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.adjustment import utc_now
from bedrock.models.base import Base

StoredEngine = Literal["mean", "arima", "ets", "blend", "stl"]
STORED_ENGINES: tuple[str, ...] = get_args(StoredEngine)


class DriverEngineChoice(Base):
    """The forecast engine a scenario uses for one driver's default, shared by its three cases
    (docs/erd/forecasting.md "Statistical engines (M6)"). Only non-`auto` choices are stored: a
    missing row is `auto`."""

    __tablename__ = "driver_engine_choice"
    __table_args__ = (
        UniqueConstraint("scenario_id", "driver_code"),
        CheckConstraint(
            "engine_code IN ('mean', 'arima', 'ets', 'blend', 'stl')", name="engine_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False
    )
    driver_code: Mapped[str] = mapped_column(String(80), nullable=False)
    # one of STORED_ENGINES
    engine_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # always null in M6 (reserved for blend weights)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
