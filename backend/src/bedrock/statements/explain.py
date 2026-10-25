"""Cell details: where one statement value came from. Pure."""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.vintage import BALANCE_DATE_TOLERANCE
from bedrock.statements.cell_types import Derivation, Provenance
from bedrock.statements.cells import compute_cells
from bedrock.statements.normalize import AdjustmentLike, AppliedAdjustment, apply_adjustments
from bedrock.statements.periods import annual_periods, fiscal_calendar, quarterly_periods
from bedrock.statements.rules import NO_RULES, Rules


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
    # M2: the adjustments that change this cell, and its value once they are applied (None when no
    # adjustment changes the cell, or when normalization empties it, then `adjustments` is
    # non-empty); `value` stays the reported figure
    adjustments: list[AppliedAdjustment] = field(default_factory=list)
    normalized_value: Decimal | None = None


def explain_cell(
    frame: pd.DataFrame,
    all_vintages: pd.DataFrame,
    items: Sequence[CanonicalItemDef],
    code: str,
    fiscal_year: int,
    fiscal_period: str,
    adjustments: Sequence[AdjustmentLike] = (),
    rules: Rules = NO_RULES,
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
    cells = compute_cells(frame, items, calendar, rules)
    cell = cells[(code, period.key)]
    normalized, applied = apply_adjustments(cells, items, adjustments, calendar, rules.identities)
    behind = applied.get((code, period.key), [])

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
        adjustments=behind,
        normalized_value=normalized[(code, period.key)].value if behind else None,
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
    """The cell's value as each filing reported it, oldest first. `concept` may be a summed
    concept (`A + B`, see `map_facts`): its vintage at a filing is the sum of every member's latest
    value filed on or before that filing, so the last vintage is the value the cell shows. A filing
    counts when it carries any member and the anchor has a value by then."""
    members = concept.split(" + ")
    by_member: dict[str, list[dict[Hashable, Any]]] = {name: [] for name in members}
    for r in facts.to_dict("records"):
        if (
            r["taxonomy"] == taxonomy
            and r["concept"] in by_member
            and r["unit"] == unit
            and (
                (r["period_start"] == start and r["period_end"] == end)
                # an instant's balance date may sit up to a week off the one the cell reads
                # (`select_vintage` groups them), and every filing of the group is a vintage
                or (
                    start is None
                    and pd.isna(r["period_start"])
                    and abs(r["period_end"] - end) <= BALANCE_DATE_TOLERANCE
                )
            )
        ):
            by_member[r["concept"]].append(r)
    for rows in by_member.values():
        rows.sort(key=_filed_key)

    filings = sorted({_filed_key(r): r for rows in by_member.values() for r in rows}.items())
    vintages: list[Vintage] = []
    for key, filing in filings:
        known = [
            [r for r in rows if _filed_key(r) <= key][-1:]  # the member's latest value as of then
            for rows in by_member.values()
        ]
        if not known[0]:  # the anchor has no value yet
            continue
        total = sum((r["value"] for rows in known for r in rows), Decimal(0))
        vintages.append(
            Vintage(total * sign, filing["accession_no"], filing["form"], filing["filed_at"])
        )
    return vintages


def _filed_key(row: dict[Hashable, Any]) -> tuple[date, str]:
    return (row["filed_at"], row["accession_no"])
