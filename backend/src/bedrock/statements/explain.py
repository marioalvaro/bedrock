"""Cell details: where one statement value came from. Pure."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.cells import Derivation, Provenance, compute_cells
from bedrock.statements.periods import annual_periods, fiscal_calendar, quarterly_periods


@dataclass(frozen=True)
class SourceInfo:
    taxonomy: str
    concept: str
    unit: str


@dataclass(frozen=True)
class FilingInfo:
    accession_no: str
    form: str
    filed_at: date


@dataclass(frozen=True)
class Vintage:
    value: Decimal  # with the item's sign applied, like the cell
    accession_no: str
    form: str
    filed_at: date


@dataclass(frozen=True)
class CellExplanation:
    code: str
    label: str
    fiscal_year: int
    fiscal_period: str
    value: Decimal | None
    provenance: Provenance | None
    source: SourceInfo | None  # reported cells
    filing: FilingInfo | None  # reported cells
    derivation: Derivation | None  # derived cells
    vintages: list[Vintage]  # every filing's value of the source fact, oldest first


def explain_cell(
    frame: pd.DataFrame,
    all_vintages: pd.DataFrame,
    items: Sequence[CanonicalItemDef],
    code: str,
    fiscal_year: int,
    fiscal_period: str,
) -> CellExplanation:
    """`frame` is the canonical (latest) frame, `all_vintages` the fact frame before
    `select_vintage`. Raises KeyError for an unknown code or a period that does not exist."""
    item = next((i for i in items if i.code == code), None)
    if item is None:
        raise KeyError(code)
    calendar = fiscal_calendar(frame)
    period = next(
        (
            p
            for p in annual_periods(calendar) + quarterly_periods(calendar)
            if (p.fiscal_year, p.fiscal_period) == (fiscal_year, fiscal_period)
        ),
        None,
    )
    if period is None:
        raise KeyError(f"FY{fiscal_year} {fiscal_period}")
    cell = compute_cells(frame, items, calendar)[(code, period.key)]

    source = filing = None
    vintages: list[Vintage] = []
    if cell.source is not None:
        ref = cell.source
        source = SourceInfo(ref.taxonomy, ref.concept, ref.unit)
        filing = FilingInfo(ref.accession_no, ref.form, ref.filed_at)
        vintages = _vintages(
            all_vintages,
            ref.taxonomy,
            ref.concept,
            ref.unit,
            ref.period_start,
            ref.period_end,
            item.sign,
        )
    return CellExplanation(
        code=code,
        label=item.label,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        value=cell.value,
        provenance=cell.provenance,
        source=source,
        filing=filing,
        derivation=cell.derivation,
        vintages=vintages,
    )


def _vintages(
    facts: pd.DataFrame,
    taxonomy: str,
    concept: str,
    unit: str,
    start: date | None,
    end: date,
    sign: int,
) -> list[Vintage]:
    rows = [
        r
        for r in facts.to_dict("records")
        if (r["taxonomy"], r["concept"], r["unit"], r["period_end"])
        == (taxonomy, concept, unit, end)
        and (r["period_start"] == start or (start is None and pd.isna(r["period_start"])))
    ]
    rows.sort(key=lambda r: (r["filed_at"], r["accession_no"]))
    return [Vintage(r["value"] * sign, r["accession_no"], r["form"], r["filed_at"]) for r in rows]
