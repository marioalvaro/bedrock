"""The real pipeline over a recorded companyfacts fixture, for the golden and regression tests.

fixture -> parse -> fact frame -> vintage -> mapper (shipped YAML + overrides) -> statements.
No DB and no network: it is the same chain `build_statements` runs in S4, minus the repository.
"""

import csv
import gzip
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path

import pandas as pd

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.xbrl import is_standard_taxonomy, parse_filing
from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_OVERRIDES_DIR,
    CanonicalItemDef,
    IdentityDef,
    covers_text,
    load_canonical_items,
    load_excludes,
    load_identities,
    load_other_lines,
    load_overrides,
    parse_formula,
    signed_members,
)
from bedrock.mapping.mapper import CANONICAL_COLUMNS, map_facts
from bedrock.mapping.vintage import balance_snapshot, select_vintage
from bedrock.services.coverage import CompanyCoverage, coverage_of, evidence_concepts
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.imports import StoredValue, company_calendar, imported_frames
from bedrock.statements.periods import Calendar
from bedrock.statements.rules import Rules, filings_tagging_nci
from bedrock.statements.splits import split_adjust
from bedrock.statements.structure import LINE_COLUMNS, FaceLines, face_concepts

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
SPLITS = Path(__file__).parent / "fixtures" / "yfinance"
STATEMENTS = ("IS", "BS", "CF")


@dataclass(frozen=True)
class Pipeline:
    items: list[CanonicalItemDef]
    facts: pd.DataFrame  # every vintage of the mapped concepts
    mappings: pd.DataFrame
    canonical: pd.DataFrame
    identities: list[IdentityDef]
    rules: Rules
    annual: dict[str, StatementTable]
    quarterly: dict[str, StatementTable]


def mapping_frame(
    items: list[CanonicalItemDef],
    overrides: dict[str, list[str]],
    excludes: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Defaults (less the company's `excludes`; priorities keep their place) and its overrides."""
    rows: list[dict[str, object]] = []
    dropped = excludes or {}
    for item in items:
        for is_override, concepts in ((False, item.concepts), (True, overrides.get(item.code, []))):
            for priority, entry in enumerate(concepts):
                if not is_override and entry in dropped.get(item.code, []):
                    continue
                # a summed concept: one row per member, each with its weight
                for weight, taxonomy, name in signed_members(entry):
                    rows.append(
                        {
                            "canonical_code": item.code,
                            "taxonomy": taxonomy,
                            "concept": name,
                            "priority": priority,
                            "is_override": is_override,
                            "weight": weight,
                            "covers": None if is_override else covers_text(item, entry),
                        }
                    )
    frame = pd.DataFrame(
        rows,
        columns=[
            "canonical_code",
            "taxonomy",
            "concept",
            "priority",
            "is_override",
            "weight",
            "covers",
        ],
    )
    # an object column keeps None (plain) apart from "" (combined, covering no row), as the
    # repository's `mappings_for` does
    frame["covers"] = pd.Series([r["covers"] for r in rows], index=frame.index, dtype=object)
    return frame


@cache
def filing_fixtures(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The recorded filings of the company (`fixtures/edgar/filings/<TICKER>/`), parsed as
    `services/filings.py` does: their face lines (`LINE_COLUMNS`) and their extension-taxonomy
    facts (`FACT_COLUMNS`), each joined to its filing in the companyfacts fixture. A company
    without recorded filings has neither."""
    from bedrock.services.filings import statement_anchors

    with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
        filings = {f.accession_no: f for f in parse_companyfacts(json.load(handle)).filings}
    lines: list[tuple[object, ...]] = []
    extension: list[dict[str, object]] = []
    folder = FIXTURES / "filings" / ticker
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        filing = filings[path.name]
        files = {
            p.name.removesuffix(".gz"): gzip.decompress(p.read_bytes()) for p in path.iterdir()
        }
        parsed = parse_filing(files, statement_anchors(ticker), accession_no=path.name)
        for line in parsed.lines:
            lines.append(
                (
                    path.name,
                    filing.form,
                    filing.filed_at,
                    line.statement,
                    line.position,
                    line.taxonomy,
                    line.concept,
                    line.label,
                    line.calc_parent_taxonomy,
                    line.calc_parent_concept,
                    line.calc_weight,
                )
            )
        extension += [
            {
                "taxonomy": f.taxonomy,
                "concept": f.concept,
                "unit": f.unit,
                "period_start": f.period_start,
                "period_end": f.period_end,
                "value": f.value,
                "accession_no": path.name,
                "form": filing.form,
                "filed_at": filing.filed_at,
            }
            for f in parsed.facts
            if not is_standard_taxonomy(f.taxonomy)
        ]
    line_frame = pd.DataFrame(lines, columns=LINE_COLUMNS).astype({"calc_weight": "object"})
    facts = pd.DataFrame(extension, columns=FACT_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )
    return line_frame, facts


def face_lines(ticker: str, mappings: pd.DataFrame, as_of: date | None) -> FaceLines | None:
    """What `services/statements.py::_face_lines` gives for the fixture company."""
    from bedrock.services.statements import concept_triage

    lines, _ = filing_fixtures(ticker)
    lines = _filed_by(lines, as_of)
    if lines.empty:
        return None
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    concepts = face_concepts(lines, items)
    every = all_facts(ticker)
    facts = every[
        [key in concepts for key in zip(every["taxonomy"], every["concept"], strict=True)]
    ]
    return FaceLines(
        lines,
        _filed_by(facts, as_of),
        mappings,
        {key: verdict.codes for key, verdict in concept_triage().items()},
        frozenset(load_other_lines(DEFAULT_OVERRIDES_DIR, ticker)),
    )


def fact_frame(ticker: str, mappings: pd.DataFrame) -> pd.DataFrame:
    """All vintages of the concepts the mappings reference, joined to their filing: the
    companyfacts fixture's, and the extension facts of the recorded filings (stored with
    `source="filing"` in the database)."""
    every = all_facts(ticker)
    wanted = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
    return every[[key in wanted for key in zip(every["taxonomy"], every["concept"], strict=True)]]


def _companyfacts_frame(ticker: str) -> pd.DataFrame:
    with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
        parsed = parse_companyfacts(json.load(handle))
    filings = {f.accession_no: f for f in parsed.filings}
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
    ]
    return pd.DataFrame(rows, columns=FACT_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )


def cover_shares(ticker: str) -> pd.DataFrame:
    """The cover-page counts of the fixture, dated on the period each filing reports, like
    `load_cover_shares`."""
    with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
        parsed = parse_companyfacts(json.load(handle))
    filings = {f.accession_no: f for f in parsed.filings}
    rows = [
        (
            "shares_outstanding",
            None,
            filings[f.accession_no].period_end,
            f.value,
            f.taxonomy,
            f.concept,
            f.unit,
            f.accession_no,
            filings[f.accession_no].form,
            filings[f.accession_no].filed_at,
            "instant",
            None,
        )
        for f in parsed.facts
        if (f.taxonomy, f.concept, f.unit)
        == ("dei", "EntityCommonStockSharesOutstanding", "shares")
    ]
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS).astype(
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
    """Every fact (any concept) of the newest 10-K, like `load_latest_annual_facts`: with the
    extension facts of that filing when it is recorded."""
    every = all_facts(ticker)
    annual = every[[str(form).startswith("10-K") for form in every["form"]]]
    newest = max(zip(annual["filed_at"], annual["accession_no"], strict=True))[1]
    return every[every["accession_no"] == newest].reset_index(drop=True)


def ten_k_dates(ticker: str) -> list[date]:
    """The filing dates of the fixture's 10-Ks, like `annual_filing_dates`."""
    with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
        parsed = parse_companyfacts(json.load(handle))
    return sorted({f.filed_at for f in parsed.filings if f.form == "10-K"})


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


def _filed_by(frame: pd.DataFrame, as_of: date | None) -> pd.DataFrame:
    """The same cut as `services/statements.py::_filed_by`; keep the two alike."""
    return frame if as_of is None else frame[frame["filed_at"] <= as_of]


def _without(items: list[CanonicalItemDef], codes: frozenset[str]) -> list[CanonicalItemDef]:
    """The items less `codes`, each formula's term for a dropped code taken out."""

    def formula(text: str | None) -> str | None:
        if text is None:
            return None
        terms = [(sign, code) for sign, code in parse_formula(text) if code not in codes]
        head = terms[0][1] if terms[0][0] > 0 else f"-{terms[0][1]}"
        return " ".join([head, *(f"{'-' if sign < 0 else '+'} {code}" for sign, code in terms[1:])])

    return [replace(i, derive=formula(i.derive)) for i in items if i.code not in codes]


@cache
def run_pipeline(
    ticker: str, as_of: date | None = None, drop_codes: frozenset[str] = frozenset()
) -> Pipeline:
    """With `as_of`, only the filings filed on or before it (docs/erd/accountability.md
    "Point-in-time history"): facts and cover-page shares. Splits are not cut. With `drop_codes`,
    the statements as built without those items (M7b S5: the history before the new rows); the
    company's overrides still load against every item."""
    all_items = load_canonical_items(DEFAULT_ITEMS_PATH)
    overrides = load_overrides(DEFAULT_OVERRIDES_DIR, ticker, all_items)
    excludes = load_excludes(DEFAULT_OVERRIDES_DIR, ticker, all_items)
    items = _without(all_items, drop_codes)
    overrides = {c: v for c, v in overrides.items() if c not in drop_codes}
    excludes = {c: v for c, v in excludes.items() if c not in drop_codes}
    mappings = mapping_frame(items, overrides, excludes)
    facts = _filed_by(fact_frame(ticker, mappings), as_of)
    latest = select_vintage(facts, snapshot=balance_snapshot(mappings))
    canonical = split_adjust(map_facts(latest, mappings, items), fixture_splits(ticker))
    identities = load_identities(DEFAULT_ITEMS_PATH, items)
    splits = fixture_splits(ticker)
    rules = Rules(
        tuple(identities),
        filings_tagging_nci(facts, mappings),
        split_adjust(_filed_by(cover_shares(ticker), as_of), splits),
        filing_lines=face_lines(ticker, mappings, as_of),
    )
    return Pipeline(
        items=items,
        facts=facts,
        mappings=mappings,
        canonical=canonical,
        identities=identities,
        rules=rules,
        annual={s: build_statement(canonical, items, s, "annual", rules=rules) for s in STATEMENTS},
        quarterly={
            s: build_statement(canonical, items, s, "quarterly", rules=rules) for s in STATEMENTS
        },
    )


def solve_with_imports(
    ticker: str, stored: Sequence[StoredValue], drop: frozenset[tuple[str, str]] = frozenset()
) -> tuple[SolvedCells, Calendar]:
    """The fixture company's cells with `stored` imported values on top. `drop` removes SEC cells
    first, as (code, period end ISO date) pairs, to open a gap the fixture does not have."""
    base = run_pipeline(ticker)
    canonical = base.canonical
    if drop:
        keep = [
            (code, end.isoformat()) not in drop
            for code, end in zip(canonical["code"], canonical["period_end"], strict=True)
        ]
        canonical = canonical[keep]
    frames = imported_frames(stored, base.items)
    rules = replace(base.rules, imported=frames.newest, imported_vintages=frames.vintages)
    calendar = company_calendar(canonical, rules.imported)
    return solve_cells(canonical, base.items, calendar, rules), calendar


@cache
def all_facts(ticker: str) -> pd.DataFrame:
    """Every fact of the fixture (any concept, every vintage), joined to its filing, with the
    extension facts of the recorded filings, as the database holds them after a backfill."""
    _, extension = filing_fixtures(ticker)
    frame = _companyfacts_frame(ticker)
    if extension.empty:
        return frame
    return pd.concat([frame, extension], ignore_index=True)


@cache
def fixture_coverage(ticker: str) -> CompanyCoverage:
    """What `services/coverage.py::company_coverage` returns for the followed fixture company."""
    pipeline = run_pipeline(ticker)
    tables = {(s, "annual"): pipeline.annual[s] for s in STATEMENTS} | {
        (s, "quarterly"): pipeline.quarterly[s] for s in STATEMENTS
    }
    every = all_facts(ticker)
    return coverage_of(
        tuple(pipeline.items),
        pipeline.mappings,
        tables,
        every[
            [
                key in evidence_concepts(pipeline.mappings)
                for key in zip(every["taxonomy"], every["concept"], strict=True)
            ]
        ],
        latest_10k_facts(ticker),
    )
