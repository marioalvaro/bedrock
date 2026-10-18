from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.ratios.calculator import RatioTable
from bedrock.ratios.registry import Category, Unit
from bedrock.schemas.statements import PeriodOut


class RatioRowOut(BaseModel):
    """One ratio. `values` is aligned with `periods`; `pct` values are fractions (0.05 = 5 %)."""

    code: str
    label: str
    category: Category
    unit: Unit
    definition: str
    caveat: str | None
    values: list[Decimal | None]


class RatiosOut(BaseModel):
    ticker: str
    freq: Literal["annual", "ttm"]
    basis: Literal["reported", "normalized"]
    periods: list[PeriodOut]
    rows: list[RatioRowOut]

    @classmethod
    def from_table(
        cls,
        table: RatioTable,
        *,
        ticker: str,
        basis: Literal["reported", "normalized"],
    ) -> "RatiosOut":
        return cls(
            ticker=ticker,
            freq=table.freq,
            basis=basis,
            periods=[PeriodOut.from_period(p) for p in table.periods],
            rows=[
                RatioRowOut(
                    code=r.code,
                    label=r.label,
                    category=r.category,
                    unit=r.unit,
                    definition=r.definition,
                    caveat=r.caveat,
                    values=r.values,
                )
                for r in table.rows
            ],
        )
