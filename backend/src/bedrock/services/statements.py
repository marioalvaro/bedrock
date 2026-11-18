"""Statements, cell details and mapping gaps of a followed company, built from stored facts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Literal

import pandas as pd
from sqlalchemy.orm import Session

from bedrock.analysis.multiples import KeyStats, balance_sheet_shares, key_stats
from bedrock.core.config import Settings
from bedrock.mapping.candidates import (
    DEFAULT_CROSSWALK_PATH,
    DEFAULT_VENDOR_PATH,
    CandidateIndex,
    load_candidate_index,
)
from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_OVERRIDES_DIR,
    CanonicalItemDef,
    IdentityDef,
    load_canonical_items,
    load_identities,
    load_other_lines,
    parse_formula,
)
from bedrock.mapping.gaps import (
    MissingItem,
    UnclassifiedLine,
    UnmappedConcept,
    missing_items,
    unclassified_lines,
    unmapped_concepts,
)
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
from bedrock.repositories import classifications as classifications_repo
from bedrock.repositories import corporate_actions as actions_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import filing_lines as lines_repo
from bedrock.repositories import imports as imports_repo
from bedrock.repositories import mappings as mappings_repo
from bedrock.repositories import prices as prices_repo
from bedrock.repositories.numeric import plain
from bedrock.services.errors import CellNotFound
from bedrock.statements.build import (
    CommonSizeBase,
    Freq,
    StatementTable,
    build_tables,
)
from bedrock.statements.cell_types import RuleWarning
from bedrock.statements.coverage import Cause, Coverage, table_coverage
from bedrock.statements.custom_lines import complete_parents, custom_items, merge_lines
from bedrock.statements.explain import CellExplanation, explain_cell
from bedrock.statements.imports import StoredValue, company_calendar, imported_frames
from bedrock.statements.periods import annual_periods, quarterly_periods
from bedrock.statements.rules import Rules, filings_tagging_nci
from bedrock.statements.splits import split_adjust, split_factor
from bedrock.statements.structure import Concept, FaceLines, face_concepts
from bedrock.statements.view import trim_periods

__all__ = [
    "CellNotFound",
    "LabelledWarning",
    "MappingGaps",
    "StatementInputs",
    "build_statements",
    "cell_detail",
    "company_key_stats",
    "face_lines",
    "fiscal_periods",
    "load_inputs",
    "mapping_gaps",
    "statement_tables",
    "use_classification_threshold",
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


# M7d S4: `CLASSIFY_MIN_CONFIDENCE`, which mode `all` applies to a proposal. The statement services
# take no settings, so `create_app` sets it once from the app's settings; until then it is the
# setting's default.
_classification_threshold = Settings.model_fields["classify_min_confidence"].default


def use_classification_threshold(min_confidence: float) -> None:
    """Sets the confidence a proposal needs to be in force under mode `all` (called by
    `create_app` with the app's settings)."""
    global _classification_threshold
    _classification_threshold = min_confidence


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
    # M7b S7: face lines of the newest 10-K and 10-Q nobody classified
    unclassified_lines: list[UnclassifiedLine] = field(default_factory=list)


@dataclass(frozen=True)
class StatementInputs:
    items: tuple[CanonicalItemDef, ...]
    mappings: pd.DataFrame
    facts: pd.DataFrame  # every vintage of the mapped concepts
    canonical: pd.DataFrame  # the latest vintage, mapped and split-adjusted
    # the identities, NCI filings and imported values `build_statement` fills empty cells with
    rules: Rules
    imports: tuple[StoredValue, ...] = ()  # every imported value of the company, every vintage
    custom: tuple[CanonicalItemDef, ...] = ()  # the company's custom lines (docs/erd/data.md)

    @property
    def lines(self) -> list[CanonicalItemDef]:
        """The canonical items with the custom lines after their parents: what the statements are
        built from. Coverage, data gaps and the import template list the canonical `items`."""
        return merge_lines(self.items, self.custom)

    @property
    def empty(self) -> bool:
        """No SEC facts and no imported values: there is nothing to show."""
        no_imports = self.rules.imported is None or self.rules.imported.empty
        return self.canonical.empty and no_imports


def load_inputs(session: Session, company: Company, as_of: date | None = None) -> StatementInputs:
    """Everything the engine needs for a full statement build of the company, as known on `as_of`
    (docs/erd/accountability.md "Point-in-time history"); None is today."""
    return _load(session, company, as_of=as_of)


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
    return statement_view(session, company, statement, freq, basis, common_size_base).table


@dataclass(frozen=True)
class StatementView:
    """One statement as the statements route shows it: the trimmed table and the cause of each
    empty cell by (code, period key), as Data gaps counts them (M7b S8). TTM has no causes."""

    table: StatementTable
    causes: dict[tuple[str, str], Cause]


def statement_view(
    session: Session,
    company: Company,
    statement: str,
    freq: Freq,
    basis: Basis = "reported",
    common_size_base: CommonSizeBase = "total",
) -> StatementView:
    """`build_statements` plus `table_coverage`'s causes, from one load and one solve. A quarterly
    table is judged against the annual one (`annual_only`), as `mapping_gaps` does. Raises
    ValueError for a TTM balance sheet."""
    if (statement, freq) == ("BS", "ttm"):
        raise ValueError("TTM is only defined for flow statements, not the balance sheet")
    loaded = _load(session, company)
    if loaded.empty:
        return StatementView(StatementTable(statement, freq, [], [], None, []), {})
    adjustments = adjustments_repo.list_for(session, company.id) if basis == "normalized" else []
    wanted: list[tuple[str, Freq]] = [(statement, freq)]
    if freq == "quarterly":
        wanted.append((statement, "annual"))
    tables = build_tables(
        loaded.canonical, loaded.lines, wanted, common_size_base, adjustments, loaded.rules
    )
    table = tables[(statement, freq)]
    causes: dict[tuple[str, str], Cause] = {}
    if freq != "ttm":
        causes = table_coverage(
            table,
            loaded.items,
            set(loaded.mappings["canonical_code"]),
            table.rule_warnings,
            annual=tables.get((statement, "annual")),
        ).causes
    return StatementView(trim_periods(table), causes)


def statement_tables(
    session: Session,
    company: Company,
    wanted: Sequence[tuple[str, Freq]],
    basis: Basis = "reported",
    common_size_base: CommonSizeBase = "total",
    as_of: date | None = None,
) -> dict[tuple[str, Freq], StatementTable]:
    """Every requested (statement, freq) table on `basis`, untrimmed, from one load of the
    company's facts (and one read of its adjustments when `normalized`) and one solve of its
    cells (`statements/build.py::build_tables`), keyed in request order. `common_size_base`
    applies to every table. A company with no facts gives empty tables. Raises ValueError for a
    TTM balance sheet. With `as_of`, only what was known on that date counts (`_load`, and the
    adjustments created by then)."""
    if ("BS", "ttm") in wanted:
        raise ValueError("TTM is only defined for flow statements, not the balance sheet")
    loaded = _load(session, company, as_of=as_of)
    if loaded.empty:
        return {(s, f): StatementTable(s, f, [], [], None, []) for s, f in wanted}
    adjustments = (
        [
            a
            for a in adjustments_repo.list_for(session, company.id)
            if as_of is None or a.created_at.date() <= as_of
        ]
        if basis == "normalized"
        else []
    )
    return build_tables(
        loaded.canonical, loaded.lines, wanted, common_size_base, adjustments, loaded.rules
    )


def cell_detail(
    session: Session, company: Company, code: str, fiscal_year: int, fiscal_period: str
) -> CellExplanation:
    """The reported value and where it came from, plus the adjustments that change the cell and
    its normalized value (whichever basis the grid shows)."""
    loaded = _load(session, company)
    if loaded.empty:
        raise CellNotFound(code)
    try:
        return explain_cell(
            loaded.canonical,
            loaded.facts,
            loaded.lines,
            code,
            fiscal_year,
            fiscal_period,
            adjustments_repo.list_for(session, company.id),
            loaded.rules,
        )
    except KeyError as error:
        raise CellNotFound(str(error)) from error


def fiscal_periods(session: Session, company: Company) -> set[tuple[int, str]]:
    """The (fiscal year, FY or Qn) pairs the company's statements have. The calendar is read
    from the mapped facts and the imports, so the filing lines are not loaded for it."""
    loaded = _load(session, company, structure=False)
    if loaded.empty:
        return set()
    calendar = company_calendar(loaded.canonical, loaded.rules.imported)
    return {
        (p.fiscal_year, p.fiscal_period)
        for p in annual_periods(calendar) + quarterly_periods(calendar)
    }


def mapping_gaps(session: Session, company: Company) -> MappingGaps:
    """What the data lacks: items without values, concepts nothing maps, the coverage and causes of
    the empty cells (R6) and the rules' warnings."""
    loaded = _load(session, company)
    if loaded.empty:
        return MappingGaps([], [], [], [])
    lines = loaded.lines  # the tables are built as the statements are; coverage counts the items
    wanted: list[tuple[str, Freq]] = [
        (s, f) for s in ("IS", "BS", "CF") for f in ("annual", "quarterly")
    ]
    tables = build_tables(loaded.canonical, lines, wanted, rules=loaded.rules)
    annual = {s: tables[(s, "annual")] for s in ("IS", "BS", "CF")}
    mapped = set(loaded.mappings["canonical_code"])
    warnings = annual["IS"].rule_warnings  # the same on every table of the company
    by_code = {i.code: i for i in lines}
    latest_10k = facts_repo.load_latest_annual_facts(session, company.id)
    return MappingGaps(
        missing_items=missing_items(annual, loaded.items),
        unmapped_concepts=unmapped_concepts(
            latest_10k, loaded.mappings, candidate_index(), concept_triage()
        ),
        coverage=[
            table_coverage(t, loaded.items, mapped, warnings, annual=annual[t.statement])
            for t in tables.values()
        ],
        rule_warnings=[
            LabelledWarning(w, by_code[w.code].label, by_code[w.code].unit) for w in warnings
        ],
        unclassified_lines=unclassified_lines(loaded.rules.filing_lines, loaded.items),
    )


def company_key_stats(session: Session, company: Company) -> KeyStats:
    """The company-list stats. Only the concepts they need are loaded."""
    manual = company.source == "manual"
    loaded = _load(session, company, codes=_key_stat_codes(manual))
    close = prices_repo.latest_close(session, company.id)
    if loaded.empty:
        return key_stats(
            close=close, shares=_cover_shares(session, company), ttm={}, quarterly_bs=None
        )
    wanted: list[tuple[str, Freq]] = [("IS", "ttm"), ("CF", "ttm"), ("BS", "quarterly")]
    if manual:
        wanted.append(("BS", "annual"))
    tables = build_tables(loaded.canonical, loaded.items, wanted, rules=loaded.rules)
    ttm = {statement: tables[(statement, "ttm")] for statement in ("IS", "CF")}
    quarterly_bs = tables[("BS", "quarterly")]
    # A manual company has no cover-page count; its imported balance sheet has the shares.
    shares = (
        balance_sheet_shares(quarterly_bs, tables[("BS", "annual")])
        if manual
        else _cover_shares(session, company)
    )
    return key_stats(close=close, shares=shares, ttm=ttm, quarterly_bs=quarterly_bs)


def _cover_shares(session: Session, company: Company) -> Decimal | None:
    """The newest cover-page share count, in the shares of today (it is in those of its filing's
    day)."""
    latest = facts_repo.latest_shares_outstanding(session, company.id)
    if latest is None:
        return None
    return plain(
        latest.value * split_factor(latest.filed_at, actions_repo.list_for(session, company.id))
    )


def _load(
    session: Session,
    company: Company,
    codes: frozenset[str] | None = None,
    as_of: date | None = None,
    structure: bool = True,
) -> StatementInputs:
    """`structure=False` leaves the face lines of the filings out (no structure rule then runs):
    for a caller that reads the calendar and solves nothing. `as_of` cuts the facts and cover-page
    shares by `filed_at` (before the vintage and the NCI rule read them) and the imported values
    by import date. Splits, mappings and custom-line
    definitions are not cut (a custom line defined later simply has no values at the date)."""
    items = canonical_items()
    mappings = mappings_repo.mappings_for(session, company.id)
    if codes is not None:
        mappings = mappings[mappings["canonical_code"].isin(codes)]
    wanted = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
    facts = _filed_by(facts_repo.load_facts(session, company.id, wanted), as_of)
    # Always the balance-date snapshot: a later filing can restate one total and not the others.
    latest = select_vintage(facts, snapshot=balance_snapshot(mappings))
    actions = actions_repo.list_for(session, company.id)
    canonical = split_adjust(map_facts(latest, mappings, items), actions)
    # Only the NCI rule runs on a subset of the codes: an identity would read a line that was not
    # loaded as empty and solve it, and the cover-page count would fill a line that was not
    # loaded either.
    stored = _stored_imports(session, company, as_of)
    # Custom lines are not among the key-stat lines either.
    rows = imports_repo.list_lines(session, company.id) if codes is None else []
    custom = tuple(custom_items(items, rows))
    imported = imported_frames(
        stored if codes is None else [v for v in stored if v.line_code in codes],
        merge_lines(items, custom),
    )
    rules = Rules(
        canonical_identities() if codes is None else (),
        filings_tagging_nci(facts, mappings),
        split_adjust(_filed_by(facts_repo.load_cover_shares(session, company.id), as_of), actions)
        if codes is None
        else None,
        imported.newest,
        imported.vintages,
        complete_parents([(r.code, r.parent_code, r.children_complete) for r in rows]),
        # The structure rules, like the identities, would read an unloaded line as empty.
        face_lines(session, company, mappings, as_of) if codes is None and structure else None,
    )
    return StatementInputs(items, mappings, facts, canonical, rules, tuple(stored), custom)


def face_lines(
    session: Session,
    company: Company,
    mappings: pd.DataFrame,
    as_of: date | None,
    classified: Mapping[Concept, tuple[str, ...]] | None = None,
) -> FaceLines | None:
    """The face lines of the company's parsed filings known on `as_of`, the facts of their
    concepts, and what classifies them (M7b S7); None when no filing is parsed. `classified`
    None loads the company's effective classifications under its mode (M7d S4; not cut by
    `as_of`, like the mappings); `{}` applies none."""
    lines = lines_repo.lines_for(session, company.id, as_of)
    if lines.empty:
        return None
    if classified is None:
        classified = classifications_repo.effective(session, company, _classification_threshold)
    items = canonical_items()
    concepts = face_concepts(lines, items)
    facts = _filed_by(facts_repo.load_facts(session, company.id, concepts), as_of)
    return FaceLines(
        lines,
        facts,
        mappings,
        {key: verdict.codes for key, verdict in concept_triage().items()},
        frozenset(load_other_lines(DEFAULT_OVERRIDES_DIR, company.ticker)),
        classified,
    )


def _filed_by(frame: pd.DataFrame, as_of: date | None) -> pd.DataFrame:
    """The rows of a frame with a `filed_at` column filed on or before `as_of`."""
    return frame if as_of is None else frame[frame["filed_at"] <= as_of]


def _stored_imports(
    session: Session, company: Company, as_of: date | None = None
) -> list[StoredValue]:
    imports = {
        i.id: i
        for i in imports_repo.list_imports(session, company.id)
        if as_of is None or i.imported_at.date() <= as_of
    }
    return [
        StoredValue(
            f.import_id,
            imports[f.import_id].filename,
            imports[f.import_id].imported_at,
            f.line_code,
            f.fiscal_year,
            f.fiscal_period,
            f.period_start,
            f.period_end,
            f.value,
        )
        for f in imports_repo.list_facts(session, company.id)
        if f.import_id in imports
    ]


@cache
def _key_stat_codes(with_shares: bool) -> frozenset[str]:
    """The lines the stats read; `with_shares` adds the share count, for a company whose count
    comes from its balance sheet."""
    by_code = {item.code: item for item in canonical_items()}
    wanted = set(KEY_STAT_CODES) | {code for group in BALANCE_TOTALS for code in group}
    if with_shares:
        wanted.add("shares_outstanding")
    pending = list(wanted)
    while pending:
        item = by_code[pending.pop()]
        for _, operand in parse_formula(item.derive) if item.derive else []:
            if operand not in wanted:
                wanted.add(operand)
                pending.append(operand)
    return frozenset(wanted)
