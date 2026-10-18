from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.analysis.multiples import MultipleSummary
from bedrock.ratios.registry import Unit


class MultipleOut(BaseModel):
    """One valuation ratio. `pct` values are fractions; `percentile` is 0..1 and the range is
    null with fewer than three annual values (`n`)."""

    code: str
    label: str
    unit: Unit
    caveat: str | None
    current: Decimal | None
    min: Decimal | None
    median: Decimal | None
    max: Decimal | None
    percentile: Decimal | None
    n: int

    @classmethod
    def from_summary(cls, s: MultipleSummary) -> "MultipleOut":
        return cls(**s.__dict__)


class MultiplesOut(BaseModel):
    ticker: str
    basis: Literal["reported", "normalized"]
    price: Decimal | None
    price_date: date | None
    rows: list[MultipleOut]
