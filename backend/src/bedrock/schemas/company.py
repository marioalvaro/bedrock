from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from bedrock.services.companies import CompanyView


class CompanyCreate(BaseModel):
    ticker: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)]


class ManualCompanyCreate(BaseModel):
    ticker: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    fiscal_year_end_month: Annotated[int, Field(ge=1, le=12)]
    sic: Annotated[str, StringConstraints(pattern=r"^\d{4}$")] | None = None


class NewFilingOut(BaseModel):
    """A 10-K or 10-Q EDGAR lists that is not loaded yet (M7c, FR-DATA-23)."""

    model_config = ConfigDict(from_attributes=True)

    form: Literal["10-K", "10-Q"]
    filed_at: date
    period_end: date | None


class CompanyOut(BaseModel):
    id: int
    ticker: str
    cik: str | None = Field(description="Null for a manual company")
    name: str
    fiscal_year_end_month: int
    currency: str
    source: Literal["sec", "manual"]
    sic: str | None
    last_refreshed_at: datetime | None
    filings_parsed: int = Field(
        description="10-K and 10-Q filings (amendments included) whose XBRL is read"
    )
    filings_total: int = Field(description="10-K and 10-Q filings, amendments included")
    classification_mode: Literal["off", "accepted", "all"] = Field(
        description="What of the line classifications the statements use"
    )
    classification_source: str | None = Field(
        description="The classifier whose proposals mode `all` uses"
    )
    new_filings: list[NewFilingOut] = Field(
        description="10-Ks and 10-Qs EDGAR lists that are not loaded yet, newest first; "
        "empty for a manual company"
    )

    @field_validator("last_refreshed_at")
    @classmethod
    def _is_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite keeps no time zone, so the stored UTC time comes back naive; without a zone in
        # the JSON a browser would read it as local time.
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


# The `CompanyOut` fields read straight from the `company` row; the rest come from the view.
_COMPANY_COLUMNS = tuple(
    n
    for n in CompanyOut.model_fields
    if n not in {"filings_parsed", "filings_total", "new_filings"}
)


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
            **{name: getattr(view.company, name) for name in _COMPANY_COLUMNS},
            filings_parsed=view.filings_parsed,
            filings_total=view.filings_total,
            new_filings=[NewFilingOut.model_validate(row) for row in view.new_filings],
            price=stats.price,
            price_date=stats.price_date,
            market_cap=stats.market_cap,
            pe=stats.pe,
            ev_ebitda=stats.ev_ebitda,
            revenue_growth=stats.revenue_growth,
        )
