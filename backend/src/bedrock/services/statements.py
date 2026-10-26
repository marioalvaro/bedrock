"""Statements, cell details and mapping gaps of a followed company, built from stored facts."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal

import pandas as pd
from sqlalchemy.orm import Session

from bedrock.analysis.multiples import KeyStats, key_stats
from bedrock.mapping.candidates import (
    DEFAULT_CROSSWALK_PATH,
    DEFAULT_VENDOR_PATH,
    CandidateIndex,
    load_candidate_index,
)
from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    CanonicalItemDef,
    IdentityDef,
    load_canonical_items,
    load_identities,
    parse_formula,
)
from bedrock.mapping.gaps import MissingItem, UnmappedConcept, missing_items, unmapped_concepts
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.triage import (
    DEFAULT_TRIAGE_PATH,
    ConceptKey,
    ConceptVerdict,
    load_concept_triage,
)
from bedrock.mapping.vintage import BALANCE_TOTALS, balance_snapshot, select_vintage
from bedrock.models.company import Company
from bedrock.repositories import adjustments as adjustments_repo
from bedrock.repositories import corporate_actions as actions_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import mappings as mappings_repo
from bedrock.repositories import prices as prices_repo
from bedrock.repositories.numeric import plain
from bedrock.services.errors import CellNotFound
from bedrock.statements.build import CommonSizeBase, Freq, StatementTable, build_statement
from bedrock.statements.cell_types import RuleWarning
from bedrock.statements.coverage import Coverage, table_coverage
from bedrock.statements.explain import CellExplanation, explain_cell
from bedrock.statements.periods import annual_periods, fiscal_calendar, quarterly_periods
from bedrock.statements.rules import Rules, filings_tagging_nci
from bedrock.statements.splits import split_adjust, split_factor
from bedrock.statements.view import trim_periods

__all__ = [
    "CellNotFound",
    "LabelledWarning",
    "MappingGaps",
    "build_statements",
    "cell_detail",
    "company_key_stats",
    "fiscal_periods",
    "mapping_gaps",
    "statement_tables",
]

Basis = Literal["reported", "normalized"]

# The line items the company-list stats read; their formula operands and the balance-sheet totals
# (which the vintage snapshot needs) are added to this set.
KEY_STAT_CODES = frozenset(
    {
        "revenue",
        "net_income_common",
        "operating_income",
        "d_and_a",
        "short_term_debt",
        "long_term_debt",
        "cash",
        "short_term_investments",
    }
)


@cache
def canonical_items() -> tuple[CanonicalItemDef, ...]:
    return tuple(load_canonical_items())


@cache
def canonical_identities() -> tuple[IdentityDef, ...]:
    return tuple(load_identities(DEFAULT_ITEMS_PATH, canonical_items()))


@cache
def candidate_index() -> CandidateIndex:
    return load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, canonical_items())


@cache
def concept_triage() -> dict[ConceptKey, ConceptVerdict]:
    return load_concept_triage(DEFAULT_TRIAGE_PATH, canonical_items())


@dataclass(frozen=True)
class LabelledWarning:
    warning: RuleWarning
    label: str  # of the warning's line item
    unit: str  # of the line item, for the warning's value


@dataclass(frozen=True)
class MappingGaps:
    missing_items: list[MissingItem]
    unmapped_concepts: list[UnmappedConcept]
    coverage: list[Coverage]  # statement x (annual, quarterly), IS, BS, CF in that order
    rule_warnings: list[LabelledWarning]


@dataclass(frozen=True)
class _Loaded:
    items: tuple[CanonicalItemDef, ...]
    mappings: pd.DataFrame
    facts: pd.DataFrame  # every vintage of the mapped concepts
    canonical: pd.DataFrame  # the latest vintage, mapped and split-adjusted
    rules: Rules  # the identities and NCI filings `build_statement` fills empty cells with


def build_statements(
    session: Session,
    company: Company,
    statement: str,
    freq: Freq,
    basis: Basis = "reported",
    common_size_base: CommonSizeBase = "total",
) -> StatementTable:
    """One statement as periods x items. `normalized` is reported + the company's adjustments
    (see `statements/normalize.py`). `common_size_base` picks the common-size denominator (see
    `build_statement`). Raises ValueError for a TTM balance sheet."""
    return trim_periods(
        statement_tables(session, company, [(statement, freq)], basis, common_size_base)[
            (statement, freq)
        ]
    )


def statement_tables(
    session: Session,
    company: Company,
    wanted: Sequence[tuple[str, Freq]],
    basis: Basis = "reported",
    common_size_base: CommonSizeBase = "total",
) -> dict[tuple[str, Freq], StatementTable]:
    """Every requested (statement, freq) table on `basis`, untrimmed, from one load of the
    company's facts (and one read of its adjustments when `normalized`), keyed in request order.
    `common_size_base` applies to every table. A company with no facts gives empty tables. Raises
    ValueError for a TTM balance sheet."""
    if ("BS", "ttm") in wanted:
        raise ValueError("TTM is only defined for flow statements, not the balance sheet")
    loaded = _load(session, company)
    if loaded.canonical.empty:
        return {(s, f): StatementTable(s, f, [], [], None, []) for s, f in wanted}
    adjustments = adjustments_repo.list_for(session, company.id) if basis == "normalized" else []
    return {
        (s, f): build_statement(
            loaded.canonical, loaded.items, s, f, common_size_base, adjustments, loaded.rules
        )
        for s, f in wanted
    }


def cell_detail(
    session: Session, company: Company, code: str, fiscal_year: int, fiscal_period: str
) -> CellExplanation:
    """The reported value and where it came from, plus the adjustments that change the cell and
    its normalized value (whichever basis the grid shows)."""
    loaded = _load(session, company)
    if loaded.canonical.empty:
        raise CellNotFound(code)
    try:
        return explain_cell(
            loaded.canonical,
            loaded.facts,
            loaded.items,
            code,
            fiscal_year,
            fiscal_period,
            adjustments_repo.list_for(session, company.id),
            loaded.rules,
        )
    except KeyError as error:
        raise CellNotFound(str(error)) from error


def fiscal_periods(session: Session, company: Company) -> set[tuple[int, str]]:
    """The (fiscal year, FY or Qn) pairs the company's statements have."""
    loaded = _load(session, company)
    if loaded.canonical.empty:
        return set()
    calendar = fiscal_calendar(loaded.canonical)
    return {
        (p.fiscal_year, p.fiscal_period)
        for p in annual_periods(calendar) + quarterly_periods(calendar)
    }


def mapping_gaps(session: Session, company: Company) -> MappingGaps:
    """What the data lacks: items without values, concepts nothing maps, the coverage and causes of
    the empty cells (R6) and the rules' warnings."""
    loaded = _load(session, company)
    if loaded.canonical.empty:
        return MappingGaps([], [], [], [])
    tables = {
        (s, f): build_statement(loaded.canonical, loaded.items, s, f, rules=loaded.rules)
        for s in ("IS", "BS", "CF")
        for f in ("annual", "quarterly")
    }
    annual = {s: tables[(s, "annual")] for s in ("IS", "BS", "CF")}
    mapped = set(loaded.mappings["canonical_code"])
    warnings = annual["IS"].rule_warnings  # the same on every table of the company
    by_code = {i.code: i for i in loaded.items}
    latest_10k = facts_repo.load_latest_annual_facts(session, company.id)
    return MappingGaps(
        missing_items=missing_items(annual, loaded.items),
        unmapped_concepts=unmapped_concepts(
            latest_10k, loaded.mappings, candidate_index(), concept_triage()
        ),
        coverage=[table_coverage(t, loaded.items, mapped, warnings) for t in tables.values()],
        rule_warnings=[
            LabelledWarning(w, by_code[w.code].label, by_code[w.code].unit) for w in warnings
        ],
    )


def company_key_stats(session: Session, company: Company) -> KeyStats:
    """The company-list stats. Only the concepts they need are loaded."""
    loaded = _load(session, company, codes=_key_stat_codes())
    close = prices_repo.latest_close(session, company.id)
    latest = facts_repo.latest_shares_outstanding(session, company.id)
    # The dei count is in the shares of its filing's day; bring it to today's.
    shares = (
        None
        if latest is None
        else plain(
            latest.value * split_factor(latest.filed_at, actions_repo.list_for(session, company.id))
        )
    )
    if loaded.canonical.empty:
        return key_stats(close=close, shares=shares, ttm={}, quarterly_bs=None)
    ttm = {
        statement: build_statement(
            loaded.canonical, loaded.items, statement, "ttm", rules=loaded.rules
        )
        for statement in ("IS", "CF")
    }
    quarterly_bs = build_statement(
        loaded.canonical, loaded.items, "BS", "quarterly", rules=loaded.rules
    )
    return key_stats(close=close, shares=shares, ttm=ttm, quarterly_bs=quarterly_bs)


def _load(session: Session, company: Company, codes: frozenset[str] | None = None) -> _Loaded:
    items = canonical_items()
    mappings = mappings_repo.mappings_for(session, company.id)
    if codes is not None:
        mappings = mappings[mappings["canonical_code"].isin(codes)]
    wanted = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
    facts = facts_repo.load_facts(session, company.id, wanted)
    # Always the balance-date snapshot: a later filing can restate one total and not the others.
    latest = select_vintage(facts, snapshot=balance_snapshot(mappings))
    actions = actions_repo.list_for(session, company.id)
    canonical = split_adjust(map_facts(latest, mappings, items), actions)
    # Only the NCI rule runs on a subset of the codes: an identity would read a line that was not
    # loaded as empty and solve it, and the cover-page count would fill a line that was not
    # loaded either.
    rules = Rules(
        canonical_identities() if codes is None else (),
        filings_tagging_nci(facts, mappings),
        split_adjust(facts_repo.load_cover_shares(session, company.id), actions)
        if codes is None
        else None,
    )
    return _Loaded(items, mappings, facts, canonical, rules)


@cache
def _key_stat_codes() -> frozenset[str]:
    by_code = {item.code: item for item in canonical_items()}
    wanted = set(KEY_STAT_CODES) | {code for group in BALANCE_TOTALS for code in group}
    pending = list(wanted)
    while pending:
        item = by_code[pending.pop()]
        for _, operand in parse_formula(item.derive) if item.derive else []:
            if operand not in wanted:
                wanted.add(operand)
                pending.append(operand)
    return frozenset(wanted)
