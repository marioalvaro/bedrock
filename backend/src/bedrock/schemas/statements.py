from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.schemas.adjustments import CellAdjustmentOut
from bedrock.services.adjustments import CellAdjustment
from bedrock.services.statements import MappingGaps
from bedrock.statements.build import StatementTable
from bedrock.statements.explain import CellExplanation
from bedrock.statements.periods import Period

Provenance = Literal["reported", "derived", "normalized"]


class PeriodOut(BaseModel):
    key: str
    label: str
    fiscal_year: int
    fiscal_period: str
    period_start: date
    period_end: date
    is_forecast: bool

    @classmethod
    def from_period(cls, period: Period) -> "PeriodOut":
        """An actual (not forecast) period."""
        return cls(
            key=period.key,
            label=period.label,
            fiscal_year=period.fiscal_year,
            fiscal_period=period.fiscal_period,
            period_start=period.start,
            period_end=period.end,
            is_forecast=False,
        )


class RowOut(BaseModel):
    """One line item. The arrays are aligned with the statement's `periods`; YoY and common-size
    are fractions (0.05 = 5 %), not percentages. `common_size_base` is the label of the row
    `common_size` divides by (revenue, total assets or the row's parent)."""

    code: str
    label: str
    unit: str
    kind: str
    depth: int
    values: list[Decimal | None]
    provenance: list[Provenance | None]
    yoy: list[Decimal | None]
    common_size: list[Decimal | None]
    common_size_base: str | None
    adjustable: bool  # a normalization adjustment may target this line


class BalanceCheckOut(BaseModel):
    period_key: str
    difference: Decimal | None
    ok: bool


class StatementOut(BaseModel):
    ticker: str
    statement: Literal["IS", "BS", "CF"]
    freq: Literal["annual", "quarterly", "ttm"]
    basis: Literal["reported", "normalized"]
    currency: str
    periods: list[PeriodOut]
    rows: list[RowOut]
    balance_check: list[BalanceCheckOut] | None

    @classmethod
    def from_table(
        cls,
        table: StatementTable,
        *,
        ticker: str,
        statement: Literal["IS", "BS", "CF"],
        freq: Literal["annual", "quarterly", "ttm"],
        basis: Literal["reported", "normalized"],
        currency: str,
    ) -> "StatementOut":
        return cls(
            ticker=ticker,
            statement=statement,
            freq=freq,
            basis=basis,
            currency=currency,
            periods=[PeriodOut.from_period(p) for p in table.periods],
            rows=[
                RowOut(
                    code=r.code,
                    label=r.label,
                    unit=r.unit,
                    kind=r.kind,
                    depth=r.depth,
                    values=r.values,
                    provenance=r.provenance,
                    yoy=r.yoy,
                    common_size=r.common_size,
                    common_size_base=r.common_size_base,
                    adjustable=r.adjustable,
                )
                for r in table.rows
            ],
            balance_check=(
                None
                if table.balance_check is None
                else [
                    BalanceCheckOut(period_key=c.period_key, difference=c.difference, ok=c.ok)
                    for c in table.balance_check
                ]
            ),
        )


class SourceOut(BaseModel):
    taxonomy: str
    concept: str
    unit: str


class FilingOut(BaseModel):
    accession_no: str
    form: str
    filed_at: date


class DerivationInputOut(BaseModel):
    code: str
    fiscal_period: str
    value: Decimal


class DerivationOut(BaseModel):
    formula: str
    inputs: list[DerivationInputOut]


class VintageOut(BaseModel):
    value: Decimal
    accession_no: str
    form: str
    filed_at: date


class CellDetailOut(BaseModel):
    code: str
    label: str
    fiscal_year: int
    fiscal_period: str
    value: Decimal | None
    provenance: Provenance | None
    source: SourceOut | None
    filing: FilingOut | None
    derivation: DerivationOut | None
    vintages: list[VintageOut]
    adjustments: list[CellAdjustmentOut]  # every adjustment that changes the cell
    # the value with them applied; null when no adjustment changes the cell, or when normalization
    # empties it (then `adjustments` is non-empty)
    normalized_value: Decimal | None

    @classmethod
    def from_explanation(
        cls, cell: CellExplanation, adjustments: Sequence[CellAdjustment]
    ) -> "CellDetailOut":
        return cls(
            code=cell.code,
            label=cell.label,
            fiscal_year=cell.fiscal_year,
            fiscal_period=cell.fiscal_period,
            value=cell.value,
            provenance=cell.provenance,
            source=None
            if cell.source is None
            else SourceOut(
                taxonomy=cell.source.taxonomy, concept=cell.source.concept, unit=cell.source.unit
            ),
            filing=None
            if cell.filing is None
            else FilingOut(
                accession_no=cell.filing.accession_no,
                form=cell.filing.form,
                filed_at=cell.filing.filed_at,
            ),
            derivation=None
            if cell.derivation is None
            else DerivationOut(
                formula=cell.derivation.formula,
                inputs=[
                    DerivationInputOut(code=i.code, fiscal_period=i.fiscal_period, value=i.value)
                    for i in cell.derivation.inputs
                ],
            ),
            vintages=[
                VintageOut(
                    value=v.value, accession_no=v.accession_no, form=v.form, filed_at=v.filed_at
                )
                for v in cell.vintages
            ],
            adjustments=[CellAdjustmentOut.from_cell(a) for a in adjustments],
            normalized_value=cell.normalized_value,
        )


class MissingItemOut(BaseModel):
    code: str
    label: str
    statement: str
    missing_periods: list[str]


class UnmappedConceptOut(BaseModel):
    taxonomy: str
    concept: str
    unit: str
    latest_value: Decimal
    latest_period_end: date
    facts: int
    suggested_codes: list[str]  # canonical codes it might belong to: a hint, not a mapping


class MappingGapsOut(BaseModel):
    missing_items: list[MissingItemOut]
    unmapped_concepts: list[UnmappedConceptOut]

    @classmethod
    def from_gaps(cls, gaps: MappingGaps) -> "MappingGapsOut":
        return cls(
            missing_items=[
                MissingItemOut(
                    code=m.code,
                    label=m.label,
                    statement=m.statement,
                    missing_periods=m.missing_periods,
                )
                for m in gaps.missing_items
            ],
            unmapped_concepts=[
                UnmappedConceptOut(
                    taxonomy=u.taxonomy,
                    concept=u.concept,
                    unit=u.unit,
                    latest_value=u.latest_value,
                    latest_period_end=u.latest_period_end,
                    facts=u.facts,
                    suggested_codes=u.suggested_codes,
                )
                for u in gaps.unmapped_concepts
            ],
        )
