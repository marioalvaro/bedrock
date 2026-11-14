from collections.abc import Collection, Sequence
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

Provenance = Literal[
    "reported", "derived", "normalized", "zero_inferred", "approximated", "imported", "forecast"
]


class PeriodOut(BaseModel):
    key: str
    label: str
    fiscal_year: int
    fiscal_period: str
    period_start: date
    period_end: date
    is_forecast: bool

    @classmethod
    def from_period(cls, period: Period, is_forecast: bool = False) -> "PeriodOut":
        return cls(
            key=period.key,
            label=period.label,
            fiscal_year=period.fiscal_year,
            fiscal_period=period.fiscal_period,
            period_start=period.start,
            period_end=period.end,
            is_forecast=is_forecast,
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
    custom: bool  # a custom line, or the `Other` row of a custom breakdown
    parent: str | None  # the line a custom row sits under
    # M7b S4: per period, the codes inside a combined value (empty when it covers no row; null
    # when not combined), and the line an empty cell's amount is inside (null when not covered)
    combined_with: list[list[str] | None]
    included_in: list[str | None]


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
        forecast_keys: Collection[str] = (),
    ) -> "StatementOut":
        """`forecast_keys`: the periods that are forecast, not actual."""
        return cls(
            ticker=ticker,
            statement=statement,
            freq=freq,
            basis=basis,
            currency=currency,
            periods=[PeriodOut.from_period(p, p.key in forecast_keys) for p in table.periods],
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
                    custom=r.custom,
                    parent=r.parent,
                    combined_with=[None if c is None else list(c) for c in r.combined_with],
                    included_in=r.included_in,
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
    # M7b S4: as on the statement row (docs/erd/data-coverage.md "Combined lines")
    combined_with: list[str] | None
    included_in: str | None

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
            combined_with=None if cell.combined_with is None else list(cell.combined_with),
            included_in=cell.included_in,
        )


class MissingItemOut(BaseModel):
    code: str
    label: str
    statement: str
    missing_periods: list[str]


class ConceptClassificationOut(BaseModel):
    type: str  # disclosure | component | rejected | scope | candidate
    reason: str
    codes: list[str]  # the canonical codes the verdict is about; empty for a disclosure


class UnmappedConceptOut(BaseModel):
    taxonomy: str
    concept: str
    unit: str
    latest_value: Decimal
    latest_period_end: date
    facts: int
    suggested_codes: list[str]  # canonical codes it might belong to: a hint, not a mapping
    classification: ConceptClassificationOut | None  # the triage verdict; null while undecided


class ProvenanceCountsOut(BaseModel):
    reported: int
    derived: int
    zero_inferred: int
    approximated: int
    imported: int


class CauseCountsOut(BaseModel):
    """Empty cells by cause, in the order a cell takes them (docs/erd/data-coverage.md)."""

    no_filing_data: int  # no anchor of the statement has a value in the period
    not_applicable: int  # a rule proves the line cannot exist in the period
    included_in: int  # the value is inside another line (M7b S4)
    structural: int  # the company maps no concept to the line and it has no formula
    rule_rejected: int  # a rule produced a value that a guard refused
    annual_only: int  # quarterly: the year has a value and none of its quarters has
    extension_unclassified: int  # an unclassified filing line in the item's block (M7b S7)
    not_reported: int  # everything else


class CoverageOut(BaseModel):
    statement: Literal["IS", "BS", "CF"]
    freq: Literal["annual", "quarterly"]
    cells: int
    filled: int
    # strict: filled / (cells - no_filing_data) as a fraction; null when there is nothing to cover
    fraction: Decimal | None
    # filled / (cells - no_filing_data - not_applicable - included_in); null likewise
    fraction_applicable: Decimal | None
    by_provenance: ProvenanceCountsOut
    empty_by_cause: CauseCountsOut


class RuleWarningOut(BaseModel):
    rule: str
    code: str
    label: str
    unit: str  # of the line, for `value`
    period_key: str
    value: Decimal | None  # the refused value; null when a guard refused to solve
    reason: str


class MappingGapsOut(BaseModel):
    missing_items: list[MissingItemOut]
    unmapped_concepts: list[UnmappedConceptOut]
    coverage: list[CoverageOut]
    rule_warnings: list[RuleWarningOut]

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
                    classification=(
                        ConceptClassificationOut(
                            type=u.classification.type,
                            reason=u.classification.reason,
                            codes=list(u.classification.codes),
                        )
                        if u.classification is not None
                        else None
                    ),
                )
                for u in gaps.unmapped_concepts
            ],
            coverage=[
                CoverageOut(
                    statement=c.statement,
                    freq=c.freq,
                    cells=c.cells,
                    filled=c.filled,
                    fraction=c.fraction,
                    fraction_applicable=c.fraction_applicable,
                    by_provenance=ProvenanceCountsOut(**c.by_provenance),
                    empty_by_cause=CauseCountsOut(**c.empty_by_cause),
                )
                for c in gaps.coverage
            ],
            rule_warnings=[
                RuleWarningOut(
                    rule=w.warning.rule,
                    code=w.warning.code,
                    label=w.label,
                    unit=w.unit,
                    period_key=w.warning.period_key,
                    value=w.warning.value,
                    reason=w.warning.reason,
                )
                for w in gaps.rule_warnings
            ],
        )
