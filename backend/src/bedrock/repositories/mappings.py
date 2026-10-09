from collections.abc import Mapping, Sequence

import pandas as pd
from sqlalchemy import delete, insert, or_, select
from sqlalchemy.orm import Session

from bedrock.mapping.config import CanonicalItemDef, split_group
from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.concept_mapping import ConceptMapping

MAPPING_COLUMNS = ["canonical_code", "taxonomy", "concept", "priority", "is_override"]


def replace_mappings(
    session: Session,
    items: Sequence[CanonicalItemDef],
    overrides: Mapping[int, Mapping[str, Sequence[str]]],
) -> None:
    """Make the stored canonical items and concept mappings equal the config: the defaults, plus
    the overrides of each company (by id). Replace-all keeps the YAML the one source of truth.
    A summed concept (`A + B`) is one row per member with the same priority, anchor first."""
    session.execute(delete(ConceptMapping))
    session.execute(delete(CanonicalItem))
    session.execute(
        insert(CanonicalItem),
        [
            {
                "code": item.code,
                "statement": item.statement,
                "label": item.label,
                "kind": item.kind,
                "unit": item.unit,
                "sign": item.sign,
                "display_order": order,
                "parent_code": item.parent,
            }
            for order, item in enumerate(items)
        ],
    )
    rows: list[dict[str, object]] = []
    for item in items:
        for priority, concept in enumerate(item.concepts):
            rows.extend(_rows(item.code, concept, priority, None))
    for company_id, by_code in overrides.items():
        for code, concepts in by_code.items():
            for priority, concept in enumerate(concepts):
                rows.extend(_rows(code, concept, priority, company_id))
    if rows:
        session.execute(insert(ConceptMapping), rows)


def _rows(code: str, entry: str, priority: int, company_id: int | None) -> list[dict[str, object]]:
    return [
        {
            "canonical_code": code,
            "taxonomy": taxonomy,
            "concept": name,
            "priority": priority,
            "company_id": company_id,
        }
        for taxonomy, name in split_group(entry)
    ]


def mappings_for(session: Session, company_id: int) -> pd.DataFrame:
    """The mapping frame of a company: the defaults and its own overrides."""
    stmt = (
        select(
            ConceptMapping.canonical_code,
            ConceptMapping.taxonomy,
            ConceptMapping.concept,
            ConceptMapping.priority,
            ConceptMapping.company_id,
        )
        .where(or_(ConceptMapping.company_id.is_(None), ConceptMapping.company_id == company_id))
        .order_by(ConceptMapping.id)
    )
    records = [(r[0], r[1], r[2], r[3], r[4] is not None) for r in session.execute(stmt)]
    return pd.DataFrame(records, columns=MAPPING_COLUMNS)
