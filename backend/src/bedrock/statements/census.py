"""The coverage census: why each empty statement cell is empty, in measurement buckets. Pure.

M7b S1 (docs/erd/data-coverage.md, "Problem and baseline"). The census sits on top of
`table_coverage`: it counts the same cells and reads its `no_filing_data` and `rule_rejected`
causes, then splits the rest into the buckets the coverage work is planned against. It is a
measurement aid for `scripts/coverage_report.py`, not something the app shows.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import pandas as pd

from bedrock.mapping.candidates import CandidateIndex
from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.build import StatementTable
from bedrock.statements.cell_types import RuleWarning
from bedrock.statements.coverage import Coverage, table_coverage

Bucket = Literal[
    "statement_not_presented",
    "not_applicable",
    "included_in",
    "rule_rejected",
    "cascade",
    "fy_empty",
    "candidate_exists",
    "annual_only",
    "quarter_missing",
    "before_first_value",
    "never_any_value",
    "some_years_missing",
]
# The order of precedence: an empty cell takes the first bucket that applies.
ANNUAL_BUCKETS: tuple[Bucket, ...] = (
    "statement_not_presented",
    "not_applicable",
    "included_in",
    "rule_rejected",
    "cascade",
    "candidate_exists",
    "before_first_value",
    "never_any_value",
    "some_years_missing",
)
# The annual-style buckets after `quarter_missing` only apply to a quarter whose fiscal year has
# no annual column (a year still open).
QUARTERLY_BUCKETS: tuple[Bucket, ...] = (
    "statement_not_presented",
    "not_applicable",
    "included_in",
    "rule_rejected",
    "cascade",
    "fy_empty",
    "candidate_exists",
    "annual_only",
    "quarter_missing",
    "before_first_value",
    "never_any_value",
    "some_years_missing",
)
END_TOLERANCE = timedelta(days=7)
ANNUAL_DAYS = (350, 380)  # a candidate of an annual table lasts a year


@dataclass(frozen=True, order=True)
class CandidateFact:
    """A us-gaap fact whose concept has `code` as a candidate and that no mapping of `code` uses.
    `period_start` is None for an instant."""

    code: str
    period_start: date | None
    period_end: date


@dataclass(frozen=True)
class CensusTable:
    coverage: Coverage
    buckets: dict[tuple[str, str], Bucket]  # (code, period key) of every empty cell
    counts: dict[str, int]  # one entry per bucket of the table's frequency, in precedence order


@dataclass(frozen=True)
class Census:
    tables: dict[tuple[str, str], CensusTable]  # (statement, freq)


def census(
    tables: Mapping[tuple[str, str], StatementTable],
    items: Sequence[CanonicalItemDef],
    mapped_codes: Collection[str],
    warnings: Sequence[RuleWarning],
    candidates: Sequence[CandidateFact],
) -> Census:
    """`tables` are keyed (statement, `annual`|`quarterly`); a quarterly table reads the annual
    table of its statement, when given, for `fy_empty` and `quarter_missing`, and passes it to
    `table_coverage` for `annual_only`. `mapped_codes` and `warnings` are those `table_coverage`
    takes. Bucket definitions:
    - `statement_not_presented`: `table_coverage`'s `no_filing_data`;
    - `not_applicable`: `table_coverage`'s `not_applicable` for a line with a value in the table
      (M7b S2, before a standard's first value). A line the company never reports is
      `not_applicable` in coverage too (M7b S5) but keeps its bucket below (`candidate_exists`,
      `never_any_value`, ...), so the census still shows what could be mapped;
    - `included_in`: `table_coverage`'s `included_in` (M7b S4: inside a combined line);
    - `rule_rejected`: `table_coverage`'s `rule_rejected`;
    - `cascade`: the line is computed (it has a `derive`), so an operand is empty too;
    - `fy_empty` (quarterly): the line's cell of the same fiscal year is empty in the annual table;
    - `candidate_exists`: a candidate fact of the line ends within 7 days of the period end, of
      the line's kind (instant or flow); in an annual table a flow fact must last 350-380 days;
    - `annual_only` (quarterly): `table_coverage`'s `annual_only`;
    - `quarter_missing` (quarterly): the year has an annual value and another quarter has one;
    - `before_first_value`: the line has a value in a later period of the table and none earlier;
    - `never_any_value`: the line has no value in any period of the table;
    - `some_years_missing`: the rest (a gap between values, or after the last one)."""
    by_code = {i.code: i for i in items}
    by_line: dict[str, list[CandidateFact]] = {}
    for fact in candidates:
        by_line.setdefault(fact.code, []).append(fact)

    result: dict[tuple[str, str], CensusTable] = {}
    for key, table in tables.items():
        annual = tables.get((table.statement, "annual")) if table.freq == "quarterly" else None
        coverage = table_coverage(table, items, mapped_codes, warnings, annual=annual)
        buckets = _buckets(table, coverage, by_code, by_line, annual)
        names = ANNUAL_BUCKETS if table.freq == "annual" else QUARTERLY_BUCKETS
        counts: dict[str, int] = {name: 0 for name in names}
        for bucket in buckets.values():
            counts[bucket] += 1
        result[key] = CensusTable(coverage, buckets, counts)
    return Census(result)


def candidate_facts(
    facts: pd.DataFrame, mappings: pd.DataFrame, index: CandidateIndex
) -> list[CandidateFact]:
    """The us-gaap facts (`taxonomy`, `concept`, `period_start`, `period_end`) of a concept the
    index gives candidate codes for, once per candidate code the company does not already map that
    concept to. Sorted, without duplicates."""
    mapped = set(
        zip(mappings["canonical_code"], mappings["taxonomy"], mappings["concept"], strict=True)
    )
    found: set[CandidateFact] = set()
    for taxonomy, concept, start, end in zip(
        facts["taxonomy"], facts["concept"], facts["period_start"], facts["period_end"], strict=True
    ):
        if taxonomy != "us-gaap":
            continue
        for code in index.get((taxonomy, concept), []):
            if (code, taxonomy, concept) not in mapped:
                found.add(CandidateFact(code, None if pd.isna(start) else start, end))
    return sorted(found, key=lambda c: (c.code, c.period_end, c.period_start or c.period_end))


def _buckets(
    table: StatementTable,
    coverage: Coverage,
    by_code: Mapping[str, CanonicalItemDef],
    candidates: Mapping[str, Sequence[CandidateFact]],
    annual: StatementTable | None,
) -> dict[tuple[str, str], Bucket]:
    rows = {row.code: row for row in table.rows}
    at = {period.key: n for n, period in enumerate(table.periods)}
    annual_values = (
        {
            row.code: dict(zip((p.key for p in annual.periods), row.values, strict=True))
            for row in annual.rows
        }
        if annual is not None
        else {}
    )
    annual_keys = {p.key for p in annual.periods} if annual is not None else set()

    buckets: dict[tuple[str, str], Bucket] = {}
    for (code, key), cause in coverage.causes.items():
        period = table.periods[at[key]]
        values = rows[code].values
        bucket: Bucket
        if cause == "no_filing_data":
            bucket = "statement_not_presented"
        elif cause == "not_applicable" and any(v is not None for v in values):
            bucket = "not_applicable"
        elif cause == "included_in":
            bucket = "included_in"
        elif cause == "rule_rejected":
            bucket = "rule_rejected"
        elif by_code[code].derive is not None:
            bucket = "cascade"
        elif table.freq == "quarterly" and f"FY{period.fiscal_year}" in annual_keys:
            bucket = _quarter_bucket(
                cause,
                period.fiscal_year,
                period.end,
                by_code[code],
                candidates.get(code, ()),
                annual_values.get(code, {}),
            )
        elif _has_candidate(candidates.get(code, ()), by_code[code], period.end, table.freq):
            bucket = "candidate_exists"
        else:
            bucket = _history_bucket(values, at[key])
        buckets[(code, key)] = bucket
    return buckets


def _quarter_bucket(
    cause: str,
    fiscal_year: int,
    end: date,
    item: CanonicalItemDef,
    candidates: Sequence[CandidateFact],
    annual_values: Mapping[str, object],
) -> Bucket:
    """A quarterly candidate may be year-to-date or the full year (Q4 is FY less Q1-Q3), so only
    its end is checked."""
    if annual_values.get(f"FY{fiscal_year}") is None:
        return "fy_empty"
    if _has_candidate(candidates, item, end, "quarterly"):
        return "candidate_exists"
    return "annual_only" if cause == "annual_only" else "quarter_missing"


def _has_candidate(
    candidates: Sequence[CandidateFact], item: CanonicalItemDef, end: date, freq: str
) -> bool:
    instant = item.kind == "instant"
    for fact in candidates:
        if (fact.period_start is None) != instant or abs(fact.period_end - end) > END_TOLERANCE:
            continue
        if freq == "annual" and fact.period_start is not None:
            days = (fact.period_end - fact.period_start).days
            if not ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]:
                continue
        return True
    return False


def _history_bucket(values: Sequence[object], at: int) -> Bucket:
    filled = [n for n, v in enumerate(values) if v is not None]
    if not filled:
        return "never_any_value"
    if at < filled[0]:
        return "before_first_value"
    return "some_years_missing"
