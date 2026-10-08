"""The real pipeline over a recorded companyfacts fixture, for the golden and regression tests.

fixture -> parse -> fact frame -> vintage -> mapper (shipped YAML + overrides) -> statements.
No DB and no network: it is the same chain `build_statements` runs in S4, minus the repository.
"""

import gzip
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pandas as pd

from bedrock.ingest.parse import parse_companyfacts
from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_OVERRIDES_DIR,
    CanonicalItemDef,
    load_canonical_items,
    load_overrides,
    split_concept,
)
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import balance_snapshot, select_vintage
from bedrock.statements.build import StatementTable, build_statement

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
STATEMENTS = ("IS", "BS", "CF")


@dataclass(frozen=True)
class Pipeline:
    items: list[CanonicalItemDef]
    facts: pd.DataFrame  # every vintage of the mapped concepts
    mappings: pd.DataFrame
    canonical: pd.DataFrame
    annual: dict[str, StatementTable]
    quarterly: dict[str, StatementTable]


def mapping_frame(items: list[CanonicalItemDef], overrides: dict[str, list[str]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for item in items:
        for is_override, concepts in ((False, item.concepts), (True, overrides.get(item.code, []))):
            for priority, concept in enumerate(concepts):
                taxonomy, name = split_concept(concept)
                rows.append(
                    {
                        "canonical_code": item.code,
                        "taxonomy": taxonomy,
                        "concept": name,
                        "priority": priority,
                        "is_override": is_override,
                    }
                )
    return pd.DataFrame(
        rows, columns=["canonical_code", "taxonomy", "concept", "priority", "is_override"]
    )


def fact_frame(ticker: str, mappings: pd.DataFrame) -> pd.DataFrame:
    """All vintages of the concepts the mappings reference, joined to their filing."""
    with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
        parsed = parse_companyfacts(json.load(handle))
    filings = {f.accession_no: f for f in parsed.filings}
    wanted = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
    rows = [
        {
            "taxonomy": f.taxonomy,
            "concept": f.concept,
            "unit": f.unit,
            "period_start": f.period_start,
            "period_end": f.period_end,
            "value": f.value,
            "accession_no": f.accession_no,
            "form": filings[f.accession_no].form,
            "filed_at": filings[f.accession_no].filed_at,
        }
        for f in parsed.facts
        if (f.taxonomy, f.concept) in wanted
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "taxonomy",
            "concept",
            "unit",
            "period_start",
            "period_end",
            "value",
            "accession_no",
            "form",
            "filed_at",
        ],
    ).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )


@cache
def run_pipeline(ticker: str) -> Pipeline:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    overrides = load_overrides(DEFAULT_OVERRIDES_DIR, ticker, items)
    mappings = mapping_frame(items, overrides)
    facts = fact_frame(ticker, mappings)
    latest = select_vintage(facts, snapshot=balance_snapshot(mappings))
    canonical = map_facts(latest, mappings, items)
    return Pipeline(
        items=items,
        facts=facts,
        mappings=mappings,
        canonical=canonical,
        annual={s: build_statement(canonical, items, s, "annual") for s in STATEMENTS},
        quarterly={s: build_statement(canonical, items, s, "quarterly") for s in STATEMENTS},
    )
