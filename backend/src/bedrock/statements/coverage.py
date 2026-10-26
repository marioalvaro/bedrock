"""R6: why a statement cell is empty, and how complete each statement is. Pure.

Cells are the non-residual items of a statement times its periods. A residual absorbs gaps by
design, and the support lines of an identity (`SUPPORT_CODES`) are optional, so neither counts.
"""

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.mapping.config import SUPPORT_CODES, CanonicalItemDef
from bedrock.statements.build import RATIO_PLACES, StatementTable
from bedrock.statements.cell_types import RuleWarning

Cause = Literal["no_filing_data", "structural", "rule_rejected", "not_reported"]
CAUSES: tuple[Cause, ...] = ("no_filing_data", "structural", "rule_rejected", "not_reported")
PROVENANCES = ("reported", "derived", "zero_inferred", "approximated", "imported")


@dataclass(frozen=True)
class Coverage:
    statement: str
    freq: str
    cells: int
    filled: int
    by_provenance: dict[str, int]  # filled cells, one entry per `PROVENANCES`
    empty_by_cause: dict[str, int]  # empty cells, one entry per `CAUSES`
    # filled / (cells - no_filing_data): a period before the statement has any data is not a gap
    fraction: Decimal | None
    causes: dict[tuple[str, str], Cause]  # (code, period key) of every empty cell


def table_coverage(
    table: StatementTable,
    items: Sequence[CanonicalItemDef],
    mapped_codes: Collection[str],
    warnings: Sequence[RuleWarning],
) -> Coverage:
    """`mapped_codes` are the canonical codes the company has a concept mapping for (its defaults
    less its excludes, plus its overrides). Causes, in this order:
    - `no_filing_data`: no item of the statement has a value in the period;
    - `structural`: the item has no formula and the company maps no concept to it;
    - `rule_rejected`: a rule warning names the cell (a Q4 cell: any period of its fiscal year,
      since Q4 follows the year and the other quarters);
    - `not_reported`: everything else, including extension tags companyfacts cannot reveal."""
    wanted = {i.code for i in items if i.statement == table.statement and not _skipped(i)}
    by_code = {i.code: i for i in items}
    rows = [row for row in table.rows if row.code in wanted]
    warned = {(w.code, w.period_key) for w in warnings}
    has_data = [
        any(row.values[at] is not None for row in table.rows if not row.custom)
        for at in range(len(table.periods))
    ]

    causes: dict[tuple[str, str], Cause] = {}
    provenance: Counter[str] = Counter()
    for row in rows:
        structural = by_code[row.code].derive is None and row.code not in mapped_codes
        for at, period in enumerate(table.periods):
            if row.values[at] is not None:
                provenance[row.provenance[at] or "reported"] += 1
                continue
            if not has_data[at]:
                cause: Cause = "no_filing_data"
            elif structural:
                cause = "structural"
            elif _rejected(row.code, period.key, period.fiscal_year, period.fiscal_period, warned):
                cause = "rule_rejected"
            else:
                cause = "not_reported"
            causes[(row.code, period.key)] = cause

    cells = len(rows) * len(table.periods)
    filled = cells - len(causes)
    empty = Counter(causes.values())
    applicable = cells - empty["no_filing_data"]
    return Coverage(
        table.statement,
        table.freq,
        cells,
        filled,
        {name: provenance[name] for name in PROVENANCES},
        {name: empty[name] for name in CAUSES},
        (Decimal(filled) / Decimal(applicable)).quantize(RATIO_PLACES) if applicable else None,
        causes,
    )


def _skipped(item: CanonicalItemDef) -> bool:
    return item.residual or item.code in SUPPORT_CODES


def _rejected(
    code: str, key: str, fiscal_year: int, fiscal_period: str, warned: set[tuple[str, str]]
) -> bool:
    if fiscal_period != "Q4":
        return (code, key) in warned
    year = f"FY{fiscal_year}"
    return any(c == code and (k == year or k.startswith(f"{year}Q")) for c, k in warned)
