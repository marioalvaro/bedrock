"""What could not be mapped (FR-DATA-04): items without values, and concepts nothing maps. Pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.build import StatementTable

IGNORED_TAXONOMIES = {"dei"}  # cover-page facts (share counts, dates), not line items


@dataclass(frozen=True)
class MissingItem:
    code: str
    label: str
    statement: str
    missing_periods: list[str]  # period keys of the fiscal years with no value


@dataclass(frozen=True)
class UnmappedConcept:
    taxonomy: str
    concept: str
    unit: str
    latest_value: Decimal
    latest_period_end: date
    facts: int  # how many facts of this concept the latest 10-K carries


def missing_items(
    tables: Mapping[str, StatementTable], items: Sequence[CanonicalItemDef]
) -> list[MissingItem]:
    """Non-residual items with no value in some fiscal year. Residuals absorb gaps by design,
    so they are never reported. Pass the annual table of each statement."""
    missing: list[MissingItem] = []
    for item in items:
        table = tables.get(item.statement)
        if item.residual or table is None:
            continue
        row = next((r for r in table.rows if r.code == item.code), None)
        if row is None:
            continue
        periods = [
            p.key
            for p, value in zip(table.periods, row.values, strict=True)
            if p.fiscal_period == "FY" and value is None
        ]
        if periods:
            missing.append(MissingItem(item.code, item.label, item.statement, periods))
    return missing


def unmapped_concepts(facts: pd.DataFrame, mappings: pd.DataFrame) -> list[UnmappedConcept]:
    """Concepts with a fact in the latest 10-K accession that no mapping references."""
    annual = facts[[str(form).startswith("10-K") for form in facts["form"]]]
    if annual.empty:
        return []
    latest = max(zip(annual["filed_at"], annual["accession_no"], strict=True))[1]
    mapped = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
    groups: dict[tuple[str, str, str], list[tuple[date, Decimal]]] = {}
    for r in annual[annual["accession_no"] == latest].itertuples(index=False):
        if r.taxonomy in IGNORED_TAXONOMIES or (r.taxonomy, r.concept) in mapped:
            continue
        groups.setdefault((r.taxonomy, r.concept, r.unit), []).append((r.period_end, r.value))
    result = []
    for (taxonomy, concept, unit), observations in sorted(groups.items()):
        period_end, value = max(observations, key=lambda o: o[0])
        result.append(
            UnmappedConcept(taxonomy, concept, unit, value, period_end, len(observations))
        )
    return result
