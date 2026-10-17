from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import BaseModel, field_validator

from bedrock.analysis.capital_allocation import CapitalAllocationTable, CapitalUnit
from bedrock.analysis.formula import Formula
from bedrock.analysis.qoe import Direction, Level, RuleUnit, Severity
from bedrock.models.off_balance_item import OffBalanceItem, OffBalanceKind
from bedrock.schemas.statements import PeriodOut
from bedrock.services.analysis import Flags, OffBalanceInput


class OffBalanceItemIn(BaseModel):
    """`amount` is in USD units."""

    kind: OffBalanceKind
    description: str
    amount: Decimal | None = None
    as_of: date
    source_note: str | None = None

    def to_input(self) -> OffBalanceInput:
        return OffBalanceInput(**self.model_dump())


class OffBalanceItemOut(BaseModel):
    id: int
    kind: OffBalanceKind
    description: str
    amount: Decimal | None
    as_of: date
    source_note: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        # SQLite keeps no time zone: without a zone in the JSON a browser reads local time.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_model(cls, item: OffBalanceItem) -> "OffBalanceItemOut":
        return cls(
            id=item.id,
            kind=cast(OffBalanceKind, item.kind),  # stored only through KINDS validation
            description=item.description,
            amount=item.amount,
            as_of=item.as_of,
            source_note=item.source_note,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class FlagRuleOut(BaseModel):
    """One rule's values and severities, aligned with `periods`; `warn`/`alert` are the effective
    number levels and `warn_formula`/`alert_formula` the formula ones (as typed), with
    `warn_levels`/`alert_levels` each level's value per period. A null value has a null
    severity. `error` is set when a stored formula of the rule no longer parses."""

    code: str
    label: str
    rule: str
    direction: Direction
    unit: RuleUnit
    warn: Decimal | None
    alert: Decimal | None
    values: list[Decimal | None]
    severity: list[Severity | None]
    custom: bool
    warn_formula: str | None
    alert_formula: str | None
    warn_levels: list[Decimal | None]
    alert_levels: list[Decimal | None]
    error: str | None


def _number(level: Level) -> Decimal | None:
    return level if isinstance(level, Decimal) else None


def _formula_text(level: Level) -> str | None:
    return level.text if isinstance(level, Formula) else None


class FlagsOut(BaseModel):
    ticker: str
    freq: Literal["annual", "ttm"]
    periods: list[PeriodOut]
    rules: list[FlagRuleOut]
    off_balance_items: list[OffBalanceItemOut]

    @classmethod
    def from_flags(cls, flags: Flags, *, ticker: str) -> "FlagsOut":
        table = flags.table
        return cls(
            ticker=ticker,
            freq=table.freq,
            periods=[PeriodOut.from_period(p) for p in table.periods],
            rules=[
                FlagRuleOut(
                    code=r.code,
                    label=r.label,
                    rule=r.rule,
                    direction=r.direction,
                    unit=r.unit,
                    warn=_number(r.thresholds.warn),
                    alert=_number(r.thresholds.alert),
                    values=r.values,
                    severity=r.severity,
                    custom=r.custom,
                    warn_formula=_formula_text(r.thresholds.warn),
                    alert_formula=_formula_text(r.thresholds.alert),
                    warn_levels=r.warn_levels,
                    alert_levels=r.alert_levels,
                    error=r.error,
                )
                for r in table.rows
            ],
            off_balance_items=[OffBalanceItemOut.from_model(i) for i in flags.off_balance_items],
        )


class CapitalRowOut(BaseModel):
    """`values` in USD (outflows negative), x or pct (fractions); `pct_of_cfo`/`pct_of_fcf` are
    null for rows that are not shares of cash flow."""

    code: str
    label: str
    unit: CapitalUnit
    values: list[Decimal | None]
    pct_of_cfo: list[Decimal | None] | None
    pct_of_fcf: list[Decimal | None] | None


class CapitalAllocationOut(BaseModel):
    ticker: str
    freq: Literal["annual", "ttm"]
    periods: list[PeriodOut]
    rows: list[CapitalRowOut]

    @classmethod
    def from_table(cls, table: CapitalAllocationTable, *, ticker: str) -> "CapitalAllocationOut":
        return cls(
            ticker=ticker,
            freq=table.freq,
            periods=[PeriodOut.from_period(p) for p in table.periods],
            rows=[
                CapitalRowOut(
                    code=r.code,
                    label=r.label,
                    unit=r.unit,
                    values=r.values,
                    pct_of_cfo=r.pct_of_cfo,
                    pct_of_fcf=r.pct_of_fcf,
                )
                for r in table.rows
            ],
        )
