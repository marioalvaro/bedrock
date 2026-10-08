from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from bedrock.services.companies import CompanyView


class CompanyCreate(BaseModel):
    ticker: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)]


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    cik: str
    name: str
    fiscal_year_end_month: int
    currency: str
    sic: str | None
    last_refreshed_at: datetime | None

    @field_validator("last_refreshed_at")
    @classmethod
    def _is_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite keeps no time zone, so the stored UTC time comes back naive; without a zone in
        # the JSON a browser would read it as local time.
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


class CompanyListItem(CompanyOut):
    """A company with its key stats (erd/workspace.md), each null when it cannot be computed."""

    price: Decimal | None = Field(description="Latest close")
    price_date: date | None
    market_cap: Decimal | None
    pe: Decimal | None
    ev_ebitda: Decimal | None
    revenue_growth: Decimal | None = Field(description="TTM revenue growth, as a fraction")

    @classmethod
    def from_view(cls, view: CompanyView) -> "CompanyListItem":
        stats = view.stats
        return cls(
            **CompanyOut.model_validate(view.company).model_dump(),
            price=stats.price,
            price_date=stats.price_date,
            market_cap=stats.market_cap,
            pe=stats.pe,
            ev_ebitda=stats.ev_ebitda,
            revenue_growth=stats.revenue_growth,
        )
