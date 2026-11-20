"""The Overview summary (M7c S6, FR-WS-04; docs/erd/workspace.md "Company summary")."""

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from bedrock.ratios.registry import Unit as RatioUnit
from bedrock.services.summary import CompanySummary


def _utc(value: datetime | None) -> datetime | None:
    # SQLite keeps no time zone: the stored UTC time comes back naive.
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


class SummaryYearOut(BaseModel):
    fiscal_year: int
    value: Decimal | None


class SummaryMetricOut(BaseModel):
    code: str
    label: str
    unit: RatioUnit
    years: list[SummaryYearOut] = Field(description="The last five fiscal years, oldest first")
    latest: Decimal | None
    yoy: Decimal | None = Field(
        description="The latest year against the one before: relative for USD and per-share "
        "units, the difference for pct and x"
    )


class SummaryFlagOut(BaseModel):
    code: str
    label: str
    severity: Literal["warn", "alert"]
    value: Decimal | None
    unit: Literal["pct", "x"]
    period_label: str


class SummaryValuationOut(BaseModel):
    scenario_id: int
    scenario_name: str
    price: Decimal | None
    price_date: date | None
    low: Decimal
    high: Decimal
    base: Decimal | None
    upside: Decimal | None


class SummaryNoteOut(BaseModel):
    id: int
    excerpt: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class SummaryForecastOut(BaseModel):
    scenario_id: int
    scenario_name: str
    updated_at: datetime
    last_snapshot_at: datetime | None
    newest_filing_date: date | None
    stale: bool = Field(description="The scenario was last edited before the newest 10-K/10-Q")

    @field_validator("updated_at", "last_snapshot_at")
    @classmethod
    def _is_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)


class CompanySummaryOut(BaseModel):
    ticker: str
    metrics: list[SummaryMetricOut]
    flags: list[SummaryFlagOut] = Field(
        description="Warn and alert rules of the newest annual period, alerts first, then by label"
    )
    valuation: SummaryValuationOut | None
    notes: list[SummaryNoteOut] = Field(description="The three newest notes")
    forecast: SummaryForecastOut | None
    warnings: list[str] = Field(description="Why a block is empty or partial")

    @classmethod
    def from_summary(cls, ticker: str, summary: CompanySummary) -> "CompanySummaryOut":
        return cls.model_validate({"ticker": ticker, **asdict(summary)})
