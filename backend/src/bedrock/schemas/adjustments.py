from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_validator

from bedrock.models.adjustment import Adjustment
from bedrock.services.adjustments import AdjustmentInput, CellAdjustment, label_of

FiscalPeriod = Literal["FY", "Q1", "Q2", "Q3", "Q4"]
Category = Literal["one-off", "restatement", "reclass", "other"]


class AdjustmentIn(BaseModel):
    """`amount` is in USD units, in the displayed sign convention: an expense is positive, so
    removing a one-off charge from SG&A is a negative amount."""

    canonical_code: str
    fiscal_year: int
    fiscal_period: FiscalPeriod
    amount: Decimal
    category: Category
    reason: str

    def to_input(self) -> AdjustmentInput:
        return AdjustmentInput(**self.model_dump())


class AdjustmentOut(BaseModel):
    id: int
    canonical_code: str
    label: str
    fiscal_year: int
    fiscal_period: str
    amount: Decimal
    category: str
    reason: str
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        # SQLite keeps no time zone: without a zone in the JSON a browser reads local time.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_model(cls, adjustment: Adjustment) -> "AdjustmentOut":
        return cls(
            id=adjustment.id,
            canonical_code=adjustment.canonical_code,
            label=label_of(adjustment.canonical_code),
            fiscal_year=adjustment.fiscal_year,
            fiscal_period=adjustment.fiscal_period,
            amount=adjustment.amount,
            category=adjustment.category,
            reason=adjustment.reason,
            created_at=adjustment.created_at,
            updated_at=adjustment.updated_at,
        )


class CellAdjustmentOut(AdjustmentOut):
    """An adjustment behind a statement cell. `via` is the adjusted line when the cell got the
    change through propagation (SG&A for the operating income it rolls into), else null."""

    via: str | None

    @classmethod
    def from_cell(cls, item: CellAdjustment) -> "CellAdjustmentOut":
        return cls(**AdjustmentOut.from_model(item.adjustment).model_dump(), via=item.via)
