"""The coverage census: the bucket of every empty cell (docs/erd/data-coverage.md, "Problem and
baseline"; M7b S1)."""

import itertools
import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cell_types import RuleWarning
from bedrock.statements.census import (
    ANNUAL_BUCKETS,
    QUARTERLY_BUCKETS,
    CandidateFact,
    candidate_facts,
    census,
)
from bedrock.statements.coverage import table_coverage
from tests.engine_data import facts, flow_facts, fy_dates, instant_facts, item, mappings
from tests.statements_pipeline import run_pipeline

ITEMS = [
    item("revenue"),
    item("cost_of_revenue"),
    item("gross_profit", derive="revenue - cost_of_revenue"),
    item("rnd"),
    item("sga"),
    item("ebit"),  # nothing maps it, no formula
    item("other_operating_expenses", residual=True, derive="gross_profit - rnd"),
    item("cash", "BS", kind="instant"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("rnd", "ResearchAndDevelopmentExpense", 0),
    ("sga", "SellingGeneralAndAdministrativeExpense", 0),
    ("cash", "Cash", 0),
)
MAPPED = set(MAPS["canonical_code"])
ALL = (1, 1, 1, 1)


def _tables(raw: list[dict[str, object]]) -> dict[tuple[str, str], StatementTable]:
    canonical = map_facts(select_vintage(facts(raw)), MAPS, ITEMS)
    return {
        (s, f): build_statement(canonical, ITEMS, s, f)  # type: ignore[arg-type]
        for s in ("IS", "BS")
        for f in ("annual", "quarterly")
    }


RAW = (
    flow_facts("Revenues", {fy: ALL for fy in (2021, 2022, 2023, 2024)})
    + flow_facts("CostOfRevenue", {2023: ALL, 2024: ALL})
    + flow_facts("ResearchAndDevelopmentExpense", {2021: ALL, 2024: ALL})
    + instant_facts("Cash", {fy: ALL for fy in (2022, 2023, 2024)})
)
TABLES = _tables(RAW)
_, FY2022_END, _ = fy_dates(2022)
SGA_CANDIDATE = CandidateFact("sga", FY2022_END - timedelta(days=364), FY2022_END)


def run(candidates: tuple[CandidateFact, ...] = (), warnings: tuple[RuleWarning, ...] = ()):  # type: ignore[no-untyped-def]
    return census(TABLES, ITEMS, MAPPED, warnings, candidates)


def annual(candidates: tuple[CandidateFact, ...] = (), warnings: tuple[RuleWarning, ...] = ()):  # type: ignore[no-untyped-def]
    return run(candidates, warnings).tables[("IS", "annual")].buckets


# --- annual buckets --------------------------------------------------------------------------


def test_a_period_in_which_the_statement_has_no_value_is_statement_not_presented() -> None:
    buckets = run().tables[("BS", "annual")].buckets

    assert buckets[("cash", "FY2021")] == "statement_not_presented"
    assert ("cash", "FY2022") not in buckets


def test_years_before_a_lines_first_value_are_before_first_value() -> None:
    buckets = annual()

    assert buckets[("cost_of_revenue", "FY2021")] == "before_first_value"
    assert buckets[("cost_of_revenue", "FY2022")] == "before_first_value"


def test_a_computed_line_is_cascade() -> None:
    buckets = annual()

    assert buckets[("gross_profit", "FY2021")] == "cascade"
    assert buckets[("gross_profit", "FY2022")] == "cascade"


def test_a_line_with_no_value_in_any_year_is_never_any_value() -> None:
    buckets = annual()

    assert {buckets[("sga", f"FY{fy}")] for fy in (2021, 2022, 2023, 2024)} == {"never_any_value"}
    assert buckets[("ebit", "FY2023")] == "never_any_value"  # structural lines too


def test_a_gap_between_values_is_some_years_missing() -> None:
    buckets = annual()

    assert buckets[("rnd", "FY2022")] == "some_years_missing"
    assert buckets[("rnd", "FY2023")] == "some_years_missing"


def test_a_cell_named_by_a_rule_warning_is_rule_rejected() -> None:
    warning = RuleWarning("equity_split", "rnd", "FY2022", Decimal(5), "refused")

    buckets = annual(warnings=(warning,))

    assert buckets[("rnd", "FY2022")] == "rule_rejected"
    assert buckets[("rnd", "FY2023")] == "some_years_missing"


def test_a_candidate_fact_for_the_period_end_is_candidate_exists() -> None:
    buckets = annual((SGA_CANDIDATE,))

    assert buckets[("sga", "FY2022")] == "candidate_exists"
    assert buckets[("sga", "FY2021")] == "never_any_value"  # another year


def test_a_candidate_within_seven_days_of_the_period_end_counts() -> None:
    near = CandidateFact("sga", FY2022_END - timedelta(days=357), FY2022_END + timedelta(days=7))
    far = CandidateFact("sga", FY2022_END - timedelta(days=356), FY2022_END + timedelta(days=8))

    assert annual((near,))[("sga", "FY2022")] == "candidate_exists"
    assert annual((far,))[("sga", "FY2022")] == "never_any_value"


def test_an_annual_table_only_counts_candidates_of_350_to_380_days() -> None:
    def lasting(days: int) -> CandidateFact:
        return CandidateFact("sga", FY2022_END - timedelta(days=days), FY2022_END)

    assert annual((lasting(350),))[("sga", "FY2022")] == "candidate_exists"
    assert annual((lasting(380),))[("sga", "FY2022")] == "candidate_exists"
    assert annual((lasting(349),))[("sga", "FY2022")] == "never_any_value"
    assert annual((lasting(381),))[("sga", "FY2022")] == "never_any_value"


def test_a_candidate_of_the_wrong_kind_does_not_count() -> None:
    instant = CandidateFact("sga", None, FY2022_END)
    flow_for_cash = CandidateFact("cash", FY2022_END - timedelta(days=364), FY2022_END)

    assert annual((instant,))[("sga", "FY2022")] == "never_any_value"
    result = run((flow_for_cash, CandidateFact("cash", None, FY2022_END)))
    assert ("cash", "FY2022") not in result.tables[("BS", "annual")].buckets  # it has a value


def test_precedence_rule_rejected_before_cascade_before_candidate() -> None:
    _, end, _ = fy_dates(2021)
    gross = CandidateFact("gross_profit", end - timedelta(days=364), end)
    cost = CandidateFact("cost_of_revenue", end - timedelta(days=364), end)
    warning = RuleWarning("identity", "gross_profit", "FY2022", None, "refused")

    buckets = annual((gross, cost), (warning,))

    assert buckets[("gross_profit", "FY2021")] == "cascade"  # a candidate does not beat cascade
    assert buckets[("gross_profit", "FY2022")] == "rule_rejected"
    assert buckets[("cost_of_revenue", "FY2021")] == "candidate_exists"  # beats before_first


def test_precedence_statement_not_presented_first() -> None:
    _, end, _ = fy_dates(2021)
    warning = RuleWarning("identity", "cash", "FY2021", None, "refused")

    buckets = run((CandidateFact("cash", None, end),), (warning,)).tables[("BS", "annual")].buckets

    assert buckets[("cash", "FY2021")] == "statement_not_presented"


# --- quarterly buckets -----------------------------------------------------------------------


def quarterly(candidates: tuple[CandidateFact, ...] = ()):  # type: ignore[no-untyped-def]
    return run(candidates).tables[("IS", "quarterly")].buckets


def test_a_quarter_of_an_empty_fiscal_year_is_fy_empty() -> None:
    buckets = quarterly()

    assert buckets[("rnd", "FY2022Q2")] == "fy_empty"
    assert buckets[("gross_profit", "FY2021Q1")] == "cascade"  # cascade still comes first


def test_quarters_of_a_year_reported_only_in_the_10k_are_annual_only() -> None:
    tenk_only = RAW + [
        r
        for r in flow_facts("SellingGeneralAndAdministrativeExpense", {2023: ALL})
        if r["form"] == "10-K"
    ]

    result = census(_tables(tenk_only), ITEMS, MAPPED, (), ())
    buckets = result.tables[("IS", "quarterly")].buckets

    assert {buckets[("sga", f"FY2023Q{n}")] for n in (1, 2, 3, 4)} == {"annual_only"}
    # the census reads the cause from `table_coverage`, which it gives the annual table
    assert result.tables[("IS", "quarterly")].coverage.empty_by_cause["annual_only"] == 4


def test_a_single_missing_quarter_in_a_reported_year_is_quarter_missing() -> None:
    raw = RAW + flow_facts("SellingGeneralAndAdministrativeExpense", {2023: ALL})
    dropped = [
        r
        for r in raw
        if not (
            r["concept"] == "SellingGeneralAndAdministrativeExpense"
            and r["accession_no"] in {"Q2-2023", "Q3-2023"}
        )
    ]

    buckets = census(_tables(dropped), ITEMS, MAPPED, (), ()).tables[("IS", "quarterly")].buckets

    assert buckets[("sga", "FY2023Q2")] == "quarter_missing"
    assert ("sga", "FY2023Q1") not in buckets


def test_a_quarterly_candidate_of_any_duration_counts_once_the_year_has_a_value() -> None:
    raw = RAW + [
        r
        for r in flow_facts("SellingGeneralAndAdministrativeExpense", {2023: ALL})
        if r["form"] == "10-K"
    ]
    _, _, q_ends = fy_dates(2023)
    start, _, _ = fy_dates(2023)
    half_year = CandidateFact("sga", start, q_ends[1])

    result = census(_tables(raw), ITEMS, MAPPED, (), (half_year,))
    buckets = result.tables[("IS", "quarterly")].buckets

    assert buckets[("sga", "FY2023Q2")] == "candidate_exists"
    assert buckets[("sga", "FY2023Q1")] == "annual_only"


def test_quarters_of_a_year_without_an_annual_column_use_the_annual_buckets() -> None:
    _, _, q_ends = fy_dates(2025)
    start, _, _ = fy_dates(2025)
    open_year = RAW + [
        {**r}
        for r in flow_facts("Revenues", {2025: ALL})
        if r["form"] == "10-Q" and r["period_end"] == q_ends[0]
    ]

    buckets = census(_tables(open_year), ITEMS, MAPPED, (), ()).tables[("IS", "quarterly")].buckets

    assert ("revenue", "FY2025Q1") not in buckets
    assert buckets[("rnd", "FY2025Q1")] == "some_years_missing"
    assert buckets[("sga", "FY2025Q1")] == "never_any_value"


# --- totals and the candidate list -----------------------------------------------------------


def test_every_empty_cell_of_table_coverage_has_one_bucket_and_the_counts_add_up() -> None:
    result = run((SGA_CANDIDATE,))

    for key, table in TABLES.items():
        entry = result.tables[key]
        coverage = table_coverage(table, ITEMS, MAPPED, (), annual=TABLES[(key[0], "annual")])
        assert set(entry.buckets) == set(coverage.causes)
        assert entry.coverage == coverage  # a quarterly table is covered with its annual one
        names = ANNUAL_BUCKETS if key[1] == "annual" else QUARTERLY_BUCKETS
        assert list(entry.counts) == list(names)
        assert sum(entry.counts.values()) == coverage.cells - coverage.filled


def test_an_empty_census_has_no_buckets() -> None:
    empty = {("IS", "annual"): StatementTable("IS", "annual", [], [], None, [])}

    result = census(empty, ITEMS, MAPPED, (), ())

    assert result.tables[("IS", "annual")].buckets == {}
    assert sum(result.tables[("IS", "annual")].counts.values()) == 0


def test_candidate_facts_are_us_gaap_facts_of_an_indexed_concept_not_mapped_to_that_code() -> None:
    raw = facts(
        [
            {
                "taxonomy": "us-gaap",
                "concept": concept,
                "unit": "USD",
                "period_start": date(2022, 1, 1),
                "period_end": date(2022, 12, 31),
                "value": Decimal(1),
                "accession_no": "a",
                "form": "10-K",
                "filed_at": date(2023, 2, 1),
            }
            for concept in ("GeneralAndAdministrativeExpense", "Revenues", "Unindexed")
        ]
        + [
            {
                "taxonomy": "dei",
                "concept": "GeneralAndAdministrativeExpense",
                "unit": "USD",
                "period_start": None,
                "period_end": date(2022, 12, 31),
                "value": Decimal(1),
                "accession_no": "a",
                "form": "10-K",
                "filed_at": date(2023, 2, 1),
            }
        ]
    )
    index = {
        ("us-gaap", "GeneralAndAdministrativeExpense"): ["sga"],
        ("us-gaap", "Revenues"): ["revenue", "other_income"],
        ("dei", "GeneralAndAdministrativeExpense"): ["sga"],
    }

    found = candidate_facts(raw, MAPS, index)

    assert sorted(found, key=lambda c: c.code) == [
        CandidateFact("other_income", date(2022, 1, 1), date(2022, 12, 31)),
        CandidateFact("sga", date(2022, 1, 1), date(2022, 12, 31)),
    ]  # Revenues already feeds revenue; dei is not us-gaap; Unindexed has no candidate


def test_candidate_facts_of_no_facts_is_empty() -> None:
    assert candidate_facts(facts([]), MAPS, {("us-gaap", "X"): ["sga"]}) == []


def test_on_a_fixture_company_the_census_matches_table_coverage() -> None:
    pipeline = run_pipeline("AAPL")
    mapped = set(pipeline.mappings["canonical_code"])
    tables = {(s, "annual"): pipeline.annual[s] for s in pipeline.annual} | {
        (s, "quarterly"): pipeline.quarterly[s] for s in pipeline.quarterly
    }
    warnings = pipeline.annual["IS"].rule_warnings

    result = census(tables, pipeline.items, mapped, warnings, ())

    for key, table in tables.items():
        coverage = table_coverage(table, pipeline.items, mapped, warnings)
        assert set(result.tables[key].buckets) == set(coverage.causes)
    assert (
        result.tables[("IS", "annual")].counts["statement_not_presented"]
        == (
            table_coverage(
                tables[("IS", "annual")], pipeline.items, mapped, warnings
            ).empty_by_cause["no_filing_data"]
        )
    )


CONCEPTS = (
    "CostOfRevenue",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
)


YEARS = (2021, 2022, 2023, 2024)
SUBSETS = [frozenset(c) for n in range(5) for c in itertools.combinations(YEARS, n)]
_rng = random.Random(17)  # hypothesis is not installed: a seeded grid of 40 cases
GRID = [
    (
        [_rng.choice(SUBSETS) for _ in CONCEPTS],
        frozenset(_rng.sample(("Q1", "Q2", "Q3"), _rng.randint(0, 3))),
        _rng.choice(SUBSETS),
    )
    for _ in range(40)
]


@pytest.mark.parametrize(("present", "dropped", "candidate_years"), GRID)
def test_every_empty_cell_gets_exactly_one_bucket_of_its_frequency(
    present: list[frozenset[int]], dropped: frozenset[str], candidate_years: frozenset[int]
) -> None:
    raw = flow_facts("Revenues", {fy: ALL for fy in (2021, 2022, 2023, 2024)})
    for concept, years in zip(CONCEPTS, present, strict=True):
        raw += [
            r
            for r in flow_facts(concept, {fy: ALL for fy in years})
            if not str(r["accession_no"]).startswith(tuple(dropped))
        ]
    tables = _tables(raw)
    candidates = tuple(
        CandidateFact("sga", fy_dates(fy)[0], fy_dates(fy)[1]) for fy in candidate_years
    )

    result = census(tables, ITEMS, MAPPED, (), candidates)

    for key, table in tables.items():
        coverage = table_coverage(table, ITEMS, MAPPED, ())
        entry = result.tables[key]
        names = ANNUAL_BUCKETS if key[1] == "annual" else QUARTERLY_BUCKETS
        assert set(entry.buckets) == set(coverage.causes)
        assert set(entry.buckets.values()) <= set(names)
        assert sum(entry.counts.values()) == coverage.cells - coverage.filled


# --- M7b S2: the census reads coverage's causes ----------------------------------------------


def test_not_applicable_is_the_second_bucket_of_both_frequencies() -> None:
    assert ANNUAL_BUCKETS[:2] == ("statement_not_presented", "not_applicable")
    assert QUARTERLY_BUCKETS[:2] == ("statement_not_presented", "not_applicable")


def test_a_line_a_standard_introduced_is_not_applicable_before_its_first_value() -> None:
    lease = replace(item("rnd"), starts_with_standard=True)
    items = [lease if i.code == "rnd" else i for i in ITEMS]
    raw = [
        r
        for r in RAW
        if not (
            r["concept"] == "ResearchAndDevelopmentExpense" and "2021" in str(r["accession_no"])
        )
    ]
    canonical = map_facts(select_vintage(facts(raw)), MAPS, items)
    tables = {
        (s, f): build_statement(canonical, items, s, f)  # type: ignore[arg-type]
        for s in ("IS",)
        for f in ("annual", "quarterly")
    }

    result = census(tables, items, MAPPED, (), (SGA_CANDIDATE,))

    annual_buckets = result.tables[("IS", "annual")].buckets
    assert {annual_buckets[("rnd", f"FY{y}")] for y in (2021, 2022, 2023)} == {"not_applicable"}
    assert result.tables[("IS", "annual")].counts["not_applicable"] == 3
    assert result.tables[("IS", "quarterly")].buckets[("rnd", "FY2022Q1")] == "not_applicable"
