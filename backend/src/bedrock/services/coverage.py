"""The coverage census of a company and the facts the coverage report reads (M7b S1).

Used by `scripts/coverage_report.py`; the app does not show the census
(docs/erd/data-coverage.md, "Problem and baseline").
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from bedrock.mapping.config import CanonicalItemDef
from bedrock.models.company import Company
from bedrock.repositories import facts as facts_repo
from bedrock.services.statements import candidate_index, load_inputs
from bedrock.statements.build import Freq, StatementTable, build_tables
from bedrock.statements.census import Census, candidate_facts, census

STATEMENTS = ("IS", "BS", "CF")
FREQS: tuple[Freq, ...] = ("annual", "quarterly")


@dataclass(frozen=True)
class CompanyCoverage:
    items: tuple[CanonicalItemDef, ...]
    mappings: pd.DataFrame
    tables: dict[tuple[str, str], StatementTable]  # (statement, annual|quarterly)
    census: Census
    # every vintage of the concepts `evidence_concepts` lists, joined to its filing
    facts: pd.DataFrame
    latest_10k: pd.DataFrame  # every fact of the newest 10-K, any concept


def evidence_concepts(mappings: pd.DataFrame) -> set[tuple[str, str]]:
    """The us-gaap concepts the candidate index gives a code for, and every mapped concept."""
    indexed = {key for key in candidate_index() if key[0] == "us-gaap"}
    return indexed | set(zip(mappings["taxonomy"], mappings["concept"], strict=True))


def coverage_of(
    items: Sequence[CanonicalItemDef],
    mappings: pd.DataFrame,
    tables: Mapping[tuple[str, str], StatementTable],
    facts: pd.DataFrame,
    latest_10k: pd.DataFrame,
) -> CompanyCoverage:
    """The census of built `tables`, with the candidate facts found in `facts`."""
    warnings = tables[("IS", "annual")].rule_warnings if tables else []
    result = census(
        tables,
        items,
        set(mappings["canonical_code"]),
        warnings,
        candidate_facts(facts, mappings, candidate_index()),
    )
    return CompanyCoverage(tuple(items), mappings, dict(tables), result, facts, latest_10k)


def company_coverage(session: Session, company: Company) -> CompanyCoverage:
    """The census of the company's six tables, built as `mapping_gaps` builds them."""
    loaded = load_inputs(session, company)
    if loaded.empty:
        return CompanyCoverage(
            loaded.items,
            loaded.mappings,
            {},
            Census({}),
            facts_repo.load_facts(session, company.id, ()),
            facts_repo.load_latest_annual_facts(session, company.id),
        )
    wanted = [(s, f) for s in STATEMENTS for f in FREQS]
    built = build_tables(loaded.canonical, loaded.lines, wanted, rules=loaded.rules)
    tables: dict[tuple[str, str], StatementTable] = dict(built.items())
    facts = facts_repo.load_facts(session, company.id, evidence_concepts(loaded.mappings))
    return coverage_of(
        loaded.items,
        loaded.mappings,
        tables,
        facts,
        facts_repo.load_latest_annual_facts(session, company.id),
    )
