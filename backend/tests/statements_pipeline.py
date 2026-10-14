"""The real pipeline over a recorded companyfacts fixture, for the golden and regression tests.

fixture -> parse -> fact frame -> vintage -> mapper (shipped YAML + overrides) -> statements.
No DB and no network: it is the same chain `build_statements` runs in S4, minus the repository.
"""

import csv
import gzip
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
    split_group,
)
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import balance_snapshot, select_vintage
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.splits import split_adjust

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
SPLITS = Path(__file__).parent / "fixtures" / "yfinance"
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
            for priority, entry in enumerate(concepts):
                for taxonomy, name in split_group(entry):  # a summed concept: one row per member
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


FACT_COLUMNS = [
    "taxonomy",
    "concept",
    "unit",
    "period_start",
    "period_end",
    "value",
    "accession_no",
    "form",
    "filed_at",
]


@cache
def latest_10k_facts(ticker: str) -> pd.DataFrame:
    """Every fact (any concept) of the newest 10-K, like `load_latest_annual_facts`."""
    with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
        parsed = parse_companyfacts(json.load(handle))
    annual = [f for f in parsed.filings if f.form.startswith("10-K")]
    newest = max(annual, key=lambda f: (f.filed_at, f.accession_no))
    rows = [
        {
            "taxonomy": f.taxonomy,
            "concept": f.concept,
            "unit": f.unit,
            "period_start": f.period_start,
            "period_end": f.period_end,
            "value": f.value,
            "accession_no": newest.accession_no,
            "form": newest.form,
            "filed_at": newest.filed_at,
        }
        for f in parsed.facts
        if f.accession_no == newest.accession_no
    ]
    return pd.DataFrame(rows, columns=FACT_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )


@dataclass(frozen=True)
class FixtureSplit:
    effective_date: date
    ratio: Decimal


def fixture_splits(ticker: str) -> list[FixtureSplit]:
    """The recorded `yfinance/<T>_splits.csv` (`date,ratio`); a missing file means no splits."""
    path = SPLITS / f"{ticker}_splits.csv"
    if not path.exists():
        return []
    with path.open() as handle:
        return [
            FixtureSplit(date.fromisoformat(r["date"]), Decimal(r["ratio"]))
            for r in csv.DictReader(handle)
        ]


@cache
def run_pipeline(ticker: str) -> Pipeline:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    overrides = load_overrides(DEFAULT_OVERRIDES_DIR, ticker, items)
    mappings = mapping_frame(items, overrides)
    facts = fact_frame(ticker, mappings)
    latest = select_vintage(facts, snapshot=balance_snapshot(mappings))
    canonical = split_adjust(map_facts(latest, mappings, items), fixture_splits(ticker))
    return Pipeline(
        items=items,
        facts=facts,
        mappings=mappings,
        canonical=canonical,
        annual={s: build_statement(canonical, items, s, "annual") for s in STATEMENTS},
        quarterly={s: build_statement(canonical, items, s, "quarterly") for s in STATEMENTS},
    )
