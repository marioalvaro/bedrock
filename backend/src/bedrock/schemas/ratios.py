from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.ratios.calculator import RatioTable
from bedrock.ratios.explain import OperandExplanation, RatioExplanation, Term
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


class TermOut(BaseModel):
    """One input of a ratio operand; a metric lists its own inputs as `children`."""

    code: str
    label: str
    kind: Literal["line", "metric", "ratio"]
    unit: str
    sign: int
    value: Decimal | None
    definition: str
    note: str | None
    children: list["TermOut"]

    @classmethod
    def from_term(cls, term: Term) -> "TermOut":
        return cls(
            code=term.code,
            label=term.label,
            kind=term.kind,
            unit=term.unit,
            sign=term.sign,
            value=term.value,
            definition=term.definition,
            note=term.note,
            children=[cls.from_term(c) for c in term.children],
        )


class OperandOut(BaseModel):
    text: str
    average: bool
    value: Decimal | None
    terms: list[TermOut]
    prior_terms: list[TermOut]

    @classmethod
    def from_operand(cls, operand: OperandExplanation) -> "OperandOut":
        return cls(
            text=operand.text,
            average=operand.average,
            value=operand.value,
            terms=[TermOut.from_term(t) for t in operand.terms],
            prior_terms=[TermOut.from_term(t) for t in operand.prior_terms],
        )


class RatioCellOut(BaseModel):
    """How one ratio value was computed: `value` = numerator ÷ denominator × `scale`."""

    code: str
    label: str
    category: Category
    unit: Unit
    definition: str
    caveat: str | None
    fiscal_year: int
    fiscal_period: str
    value: Decimal | None
    scale: Decimal
    numerator: OperandOut
    denominator: OperandOut | None
    reason: str | None

    @classmethod
    def from_explanation(cls, e: RatioExplanation) -> "RatioCellOut":
        return cls(
            code=e.code,
            label=e.label,
            category=e.category,
            unit=e.unit,
            definition=e.definition,
            caveat=e.caveat,
            fiscal_year=e.fiscal_year,
            fiscal_period=e.fiscal_period,
            value=e.value,
            scale=e.scale,
            numerator=OperandOut.from_operand(e.numerator),
            denominator=(None if e.denominator is None else OperandOut.from_operand(e.denominator)),
            reason=e.reason,
        )
