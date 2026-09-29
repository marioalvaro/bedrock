from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
