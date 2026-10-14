"""Statements, cell details and mapping gaps of a followed company, built from stored facts."""

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
from bedrock.mapping.config import CanonicalItemDef, load_canonical_items, parse_formula
from bedrock.mapping.gaps import MissingItem, UnmappedConcept, missing_items, unmapped_concepts
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import BALANCE_TOTALS, balance_snapshot, select_vintage
from bedrock.models.company import Company
from bedrock.repositories import corporate_actions as actions_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import mappings as mappings_repo
from bedrock.repositories import prices as prices_repo
from bedrock.repositories.numeric import plain
from bedrock.services.errors import CellNotFound
from bedrock.statements.build import CommonSizeBase, Freq, StatementTable, build_statement
from bedrock.statements.explain import CellExplanation, explain_cell
from bedrock.statements.splits import split_adjust, split_factor
from bedrock.statements.view import trim_periods

__all__ = [
    "CellNotFound",
    "MappingGaps",
    "build_statements",
    "cell_detail",
    "company_key_stats",
    "mapping_gaps",
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
def candidate_index() -> CandidateIndex:
    return load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, canonical_items())


@dataclass(frozen=True)
class MappingGaps:
    missing_items: list[MissingItem]
    unmapped_concepts: list[UnmappedConcept]


@dataclass(frozen=True)
class _Loaded:
    items: tuple[CanonicalItemDef, ...]
    mappings: pd.DataFrame
    facts: pd.DataFrame  # every vintage of the mapped concepts
    canonical: pd.DataFrame  # the latest vintage, mapped and split-adjusted


def build_statements(
    session: Session,
    company: Company,
    statement: str,
    freq: Freq,
    basis: Basis = "reported",
    common_size_base: CommonSizeBase = "total",
) -> StatementTable:
    """One statement as periods x items. `normalized` is the reported table until adjustments
    exist (M2). `common_size_base` picks the common-size denominator (see `build_statement`).
    Raises ValueError for a TTM balance sheet."""
    if statement == "BS" and freq == "ttm":
        raise ValueError("TTM is only defined for flow statements, not the balance sheet")
    loaded = _load(session, company)
    if loaded.canonical.empty:
        return StatementTable(statement, freq, [], [], None, [])
    return trim_periods(
        build_statement(loaded.canonical, loaded.items, statement, freq, common_size_base)
    )


def cell_detail(
    session: Session, company: Company, code: str, fiscal_year: int, fiscal_period: str
) -> CellExplanation:
    loaded = _load(session, company)
    if loaded.canonical.empty:
        raise CellNotFound(code)
    try:
        return explain_cell(
            loaded.canonical, loaded.facts, loaded.items, code, fiscal_year, fiscal_period
        )
    except KeyError as error:
        raise CellNotFound(str(error)) from error


def mapping_gaps(session: Session, company: Company) -> MappingGaps:
    loaded = _load(session, company)
    if loaded.canonical.empty:
        return MappingGaps([], [])
    annual = {
        s: build_statement(loaded.canonical, loaded.items, s, "annual") for s in ("IS", "BS", "CF")
    }
    latest_10k = facts_repo.load_latest_annual_facts(session, company.id)
    return MappingGaps(
        missing_items=missing_items(annual, loaded.items),
        unmapped_concepts=unmapped_concepts(latest_10k, loaded.mappings, candidate_index()),
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
        statement: build_statement(loaded.canonical, loaded.items, statement, "ttm")
        for statement in ("IS", "CF")
    }
    quarterly_bs = build_statement(loaded.canonical, loaded.items, "BS", "quarterly")
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
    canonical = split_adjust(
        map_facts(latest, mappings, items), actions_repo.list_for(session, company.id)
    )
    return _Loaded(items, mappings, facts, canonical)


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
