"""R6: why a statement cell is empty, and how complete each statement is. Pure.

Cells are the non-residual items of a statement times its periods. A residual absorbs gaps by
design, and the support lines of an identity (`SUPPORT_CODES`) are optional, so neither counts.
M7b S2 (docs/erd/data-coverage.md, "Coverage semantics") adds the statement anchors, the causes
of a cell that cannot exist, and the applicable fraction.
"""

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.mapping.config import SUPPORT_CODES, CanonicalItemDef
from bedrock.statements.build import RATIO_PLACES, StatementTable
from bedrock.statements.cell_types import RuleWarning

Cause = Literal[
    "no_filing_data",
    "not_applicable",
    "included_in",
    "structural",
    "rule_rejected",
    "annual_only",
    "extension_unclassified",
    "not_reported",
]
# In order: an empty cell takes the first cause that applies. `included_in` (M7b S4) and
# `extension_unclassified` (S7) are produced by later steps; they are counted from now on.
CAUSES: tuple[Cause, ...] = (
    "no_filing_data",
    "not_applicable",
    "included_in",
    "structural",
    "rule_rejected",
    "annual_only",
    "extension_unclassified",
    "not_reported",
)
# Causes of a cell that cannot hold a value: out of the applicable fraction's denominator.
INAPPLICABLE: frozenset[Cause] = frozenset({"no_filing_data", "not_applicable", "included_in"})
PROVENANCES = ("reported", "derived", "zero_inferred", "approximated", "imported")
# A period is presented on a statement when one of its anchors has a value.
STATEMENT_ANCHORS: dict[str, tuple[str, ...]] = {
    "IS": ("net_income", "net_income_common", "revenue"),
    "BS": ("total_assets", "total_liabilities_and_equity"),
    "CF": ("cfo", "net_change_in_cash"),
}


@dataclass(frozen=True)
class Coverage:
    statement: str
    freq: str
    cells: int
    filled: int
    by_provenance: dict[str, int]  # filled cells, one entry per `PROVENANCES`
    empty_by_cause: dict[str, int]  # empty cells, one entry per `CAUSES`
    # strict: filled / (cells - no_filing_data); a period the statement does not present is no gap
    fraction: Decimal | None
    causes: dict[tuple[str, str], Cause]  # (code, period key) of every empty cell
    # filled / (cells - no_filing_data - not_applicable - included_in): None with nothing left
    fraction_applicable: Decimal | None


def table_coverage(
    table: StatementTable,
    items: Sequence[CanonicalItemDef],
    mapped_codes: Collection[str],
    warnings: Sequence[RuleWarning],
    annual: StatementTable | None = None,
) -> Coverage:
    """`mapped_codes` are the canonical codes the company has a concept mapping for (its defaults
    less its excludes, plus its overrides). `annual` is the annual table of the same statement; a
    quarterly table needs it for `annual_only`. Causes, in `CAUSES` order:
    - `no_filing_data`: no anchor of the statement (`STATEMENT_ANCHORS`) has a value in the period;
    - `not_applicable`: the item `starts_with_standard` and the period is before the item's first
      value in this table (an item with no value at all gets none);
    - `structural`: the item has no formula and the company maps no concept to it;
    - `rule_rejected`: a rule warning names the cell (a Q4 cell: any period of its fiscal year,
      since Q4 follows the year and the other quarters);
    - `annual_only` (a quarterly table with `annual` given): the item has a value in the fiscal
      year's annual cell and in none of the year's quarters;
    - `not_reported`: everything else, including extension tags companyfacts cannot reveal."""
    wanted = {i.code for i in items if i.statement == table.statement and not _skipped(i)}
    by_code = {i.code: i for i in items}
    rows = [row for row in table.rows if row.code in wanted]
    warned = {(w.code, w.period_key) for w in warnings}
    anchors = [row for row in table.rows if row.code in STATEMENT_ANCHORS.get(table.statement, ())]
    presented = [
        any(row.values[at] is not None for row in anchors) for at in range(len(table.periods))
    ]
    annual_filled = _annual_filled(annual) if table.freq == "quarterly" else set()

    causes: dict[tuple[str, str], Cause] = {}
    provenance: Counter[str] = Counter()
    for row in rows:
        item = by_code[row.code]
        structural = item.derive is None and row.code not in mapped_codes
        first = next((at for at, v in enumerate(row.values) if v is not None), None)
        quarter_years = (
            {p.fiscal_year for p, v in zip(table.periods, row.values, strict=True) if v is not None}
            if annual_filled
            else set()
        )
        for at, period in enumerate(table.periods):
            if row.values[at] is not None:
                provenance[row.provenance[at] or "reported"] += 1
                continue
            if not presented[at]:
                cause: Cause = "no_filing_data"
            elif item.starts_with_standard and first is not None and at < first:
                cause = "not_applicable"
            elif structural:
                cause = "structural"
            elif _rejected(row.code, period.key, period.fiscal_year, period.fiscal_period, warned):
                cause = "rule_rejected"
            elif (
                row.code,
                period.fiscal_year,
            ) in annual_filled and period.fiscal_year not in quarter_years:
                cause = "annual_only"
            else:
                cause = "not_reported"
            causes[(row.code, period.key)] = cause

    cells = len(rows) * len(table.periods)
    filled = cells - len(causes)
    empty = Counter(causes.values())
    return Coverage(
        table.statement,
        table.freq,
        cells,
        filled,
        {name: provenance[name] for name in PROVENANCES},
        {name: empty[name] for name in CAUSES},
        _ratio(filled, cells - empty["no_filing_data"]),
        causes,
        _ratio(filled, cells - sum(empty[name] for name in INAPPLICABLE)),
    )


def _ratio(filled: int, applicable: int) -> Decimal | None:
    return (Decimal(filled) / Decimal(applicable)).quantize(RATIO_PLACES) if applicable else None


def _annual_filled(annual: StatementTable | None) -> set[tuple[str, int]]:
    """(code, fiscal year) of every non-empty annual cell."""
    if annual is None:
        return set()
    return {
        (row.code, period.fiscal_year)
        for row in annual.rows
        for period, value in zip(annual.periods, row.values, strict=True)
        if value is not None and period.fiscal_period == "FY"
    }


def _skipped(item: CanonicalItemDef) -> bool:
    return item.residual or item.code in SUPPORT_CODES


def _rejected(
    code: str, key: str, fiscal_year: int, fiscal_period: str, warned: set[tuple[str, str]]
) -> bool:
    if fiscal_period != "Q4":
        return (code, key) in warned
    year = f"FY{fiscal_year}"
    return any(c == code and (k == year or k.startswith(f"{year}Q")) for c, k in warned)
