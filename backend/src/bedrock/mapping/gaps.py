"""What could not be mapped (FR-DATA-04): items without values, and concepts nothing maps. Pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.candidates import CandidateIndex, candidate_codes
from bedrock.mapping.config import SUPPORT_CODES, CanonicalItemDef
from bedrock.mapping.triage import ConceptKey, ConceptVerdict
from bedrock.statements.build import StatementTable
from bedrock.statements.structure import FaceIndex, FaceLines

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
    suggested_codes: list[str] = field(default_factory=list)  # hints from the candidate index
    classification: ConceptVerdict | None = None  # the triage verdict, None while undecided


@dataclass(frozen=True)
class UnclassifiedLine:
    """A line on the face of the newest 10-K or 10-Q that nobody classified (M7b S7): the work
    list for the company's override file (map it, or list it under `other_lines:`)."""

    statement: str
    taxonomy: str
    concept: str
    label: str  # as the newest filing presents it
    latest_value: Decimal  # its newest fact in that filing (the longest period on that date)
    latest_period_end: date
    filings: list[str]  # the accessions presenting it, newest first


def unclassified_lines(
    face: FaceLines | None, items: Sequence[CanonicalItemDef]
) -> list[UnclassifiedLine]:
    """The lines of the newest 10-K and the newest 10-Q, per statement, whose concept nothing
    classifies (not mapped, not a face member, no triage verdict, not under `other_lines`) and
    that have a non-zero amount in their filing. Statements IS, BS, CF; lines in the newest
    filing's order."""
    if face is None or face.lines.empty:
        return []
    index = FaceIndex(face, items)
    filed = dict(zip(face.lines["accession_no"], face.lines["filed_at"], strict=True))
    forms = dict(zip(face.lines["accession_no"], face.lines["form"], strict=True))
    newest: list[str] = []
    for prefix in ("10-K", "10-Q"):
        of_form = [a for a, form in forms.items() if str(form).startswith(prefix)]
        if of_form:
            newest.append(max(of_form, key=lambda a: (filed[a], a)))
    newest.sort(key=lambda a: (filed[a], a), reverse=True)
    labels: dict[tuple[str, str, str, str], str] = {
        (str(r.accession_no), str(r.statement), str(r.taxonomy), str(r.concept)): str(r.label)
        for r in face.lines.itertuples(index=False)
    }
    found: dict[tuple[str, str, str], UnclassifiedLine] = {}
    for statement in ("IS", "BS", "CF"):
        for accession in newest:
            for line in index.statement_lines(accession, statement):
                amounts = [a for a in index.amounts.get((accession, line.concept), []) if a.value]
                if line.concept in index.known or not amounts:
                    continue
                key = (statement, *line.concept)
                if key in found:
                    found[key].filings.append(accession)
                    continue
                latest = max(amounts, key=lambda a: (a.end, -(a.start or a.end).toordinal()))
                found[key] = UnclassifiedLine(
                    statement,
                    line.concept[0],
                    line.concept[1],
                    labels[(accession, statement, *line.concept)],
                    latest.value,
                    latest.end,
                    [accession],
                )
    return list(found.values())


def missing_items(
    tables: Mapping[str, StatementTable], items: Sequence[CanonicalItemDef]
) -> list[MissingItem]:
    """Non-residual items with no value in some fiscal year. Residuals absorb gaps by design, and
    the support lines of an identity (`SUPPORT_CODES`) are optional, so neither is reported.
    Pass the annual table of each statement."""
    missing: list[MissingItem] = []
    for item in items:
        table = tables.get(item.statement)
        if item.residual or item.code in SUPPORT_CODES or table is None:
            continue
        row = table.row(item.code)
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


def unmapped_concepts(
    facts: pd.DataFrame,
    mappings: pd.DataFrame,
    index: CandidateIndex | None = None,
    triage: Mapping[ConceptKey, ConceptVerdict] | None = None,
) -> list[UnmappedConcept]:
    """Concepts with a fact in the latest 10-K accession that no mapping references. `index`
    (see `mapping/candidates.py`) adds the Bedrock codes each might belong to, and `triage` (see
    `mapping/triage.py`) the verdict already recorded for it. Order: unclassified with a
    suggestion, unclassified without one, then the classified; each group in (taxonomy, concept,
    unit) order. A classified concept keeps its suggestion."""
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
    verdicts = triage or {}
    result = []
    for (taxonomy, concept, unit), observations in sorted(groups.items()):
        period_end, value = max(observations, key=lambda o: o[0])
        suggested = candidate_codes(index, taxonomy, concept) if index is not None else []
        result.append(
            UnmappedConcept(
                taxonomy,
                concept,
                unit,
                value,
                period_end,
                len(observations),
                suggested,
                verdicts.get((taxonomy, concept)),
            )
        )
    # stable sort: keeps the (taxonomy, concept, unit) order inside each group
    return sorted(result, key=lambda u: (u.classification is not None, not u.suggested_codes))
