from datetime import datetime

from pydantic import BaseModel

from bedrock.services.refresh import RefreshResult


class RefreshResultOut(BaseModel):
    ticker: str
    new_filings: int
    new_facts: int
    new_prices: int
    new_splits: int
    new_filing_lines: int
    last_refreshed_at: datetime
    warnings: list[str]
    # M7c: the snapshot taken before a new 10-K or 10-Q was stored; null when none was
    snapshot_id: int | None

    @classmethod
    def from_result(cls, result: RefreshResult) -> "RefreshResultOut":
        return cls(
            ticker=result.ticker,
            new_filings=result.new_filings,
            new_facts=result.new_facts,
            new_prices=result.new_prices,
            new_splits=result.new_splits,
            new_filing_lines=result.new_filing_lines,
            last_refreshed_at=result.last_refreshed_at,
            warnings=result.warnings,
            snapshot_id=result.snapshot_id,
        )


class BackfillStartedOut(BaseModel):
    """A filing backfill was started; follow it with `filings_parsed` on the company."""

    ticker: str
