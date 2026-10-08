from datetime import datetime

from pydantic import BaseModel

from bedrock.services.refresh import RefreshResult


class RefreshResultOut(BaseModel):
    ticker: str
    new_filings: int
    new_facts: int
    new_prices: int
    last_refreshed_at: datetime
    warnings: list[str]

    @classmethod
    def from_result(cls, result: RefreshResult) -> "RefreshResultOut":
        return cls(
            ticker=result.ticker,
            new_filings=result.new_filings,
            new_facts=result.new_facts,
            new_prices=result.new_prices,
            last_refreshed_at=result.last_refreshed_at,
            warnings=result.warnings,
        )
