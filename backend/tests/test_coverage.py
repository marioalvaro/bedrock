"""R6: why a cell is empty, and how complete each statement is (erd/data.md, "R6")."""

from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cell_types import RuleWarning
from bedrock.statements.coverage import CAUSES, PROVENANCES, STATEMENT_ANCHORS, table_coverage
from tests import test_combined_lines
from tests.engine_data import facts, flow_facts, instant_facts, item, mappings
from tests.statements_pipeline import run_pipeline
from tests.test_statements_golden import TICKERS

ITEMS = [
    item("revenue"),
    item("cost_of_revenue", parent="gross_profit"),
    item("gross_profit", derive="revenue - cost_of_revenue"),
    # `required` (M7b S5): lines with no value in any period that must still count as gaps here
    replace(item("rnd"), required=True),
    replace(item("ebit"), required=True),  # nothing maps it, no formula: every concept excluded
    item("other_operating_expenses", residual=True, derive="gross_profit - rnd"),
    item("cash", "BS", kind="instant"),
    item("shares_issued", "BS", kind="instant", unit="shares"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("rnd", "ResearchAndDevelopmentExpense", 0),
    ("cash", "Cash", 0),
    ("shares_issued", "SharesIssued", 0),
)
MAPPED = set(MAPS["canonical_code"])
YEARS = {2021: (1, 1, 1, 1), 2022: (1, 1, 1, 1), 2023: (1, 1, 1, 1)}


def table(statement: str, freq: str) -> StatementTable:
    raw = (
        flow_facts("Revenues", YEARS)
        + flow_facts("CostOfRevenue", {2023: (1, 1, 1, 1)})
        + instant_facts("Cash", {2023: (1, 1, 1, 1)})
    )
    canonical = map_facts(select_vintage(facts(raw)), MAPS, ITEMS)
    return build_statement(canonical, ITEMS, statement, freq)  # type: ignore[arg-type]


def coverage(statement: str, freq: str, warnings: tuple[RuleWarning, ...] = ()):  # type: ignore[no-untyped-def]
    return table_coverage(table(statement, freq), ITEMS, MAPPED, warnings)


def warning(code: str, period_key: str) -> RuleWarning:
    return RuleWarning("equity_split", code, period_key, Decimal(5), "refused")


def test_a_period_before_the_statement_has_any_data_is_no_filing_data() -> None:
    causes = coverage("BS", "annual").causes

    assert causes[("cash", "FY2021")] == "no_filing_data"
    assert causes[("cash", "FY2022")] == "no_filing_data"
    assert ("cash", "FY2023") not in causes  # it has a value


def test_an_item_nothing_maps_and_no_formula_builds_is_structural() -> None:
    causes = coverage("IS", "annual").causes

    assert {causes[("ebit", f"FY{year}")] for year in YEARS} == {"structural"}


def test_an_item_with_a_formula_is_never_structural() -> None:
    causes = table_coverage(table("IS", "annual"), ITEMS, MAPPED - {"cost_of_revenue"}, ()).causes

    assert causes[("gross_profit", "FY2021")] == "not_reported"  # derive exists, operand empty
    assert causes[("cost_of_revenue", "FY2021")] == "structural"


def test_everything_else_that_is_empty_is_not_reported() -> None:
    causes = coverage("IS", "annual").causes

    assert causes[("cost_of_revenue", "FY2021")] == "not_reported"
    assert causes[("rnd", "FY2023")] == "not_reported"
    assert causes[("gross_profit", "FY2022")] == "not_reported"


def test_a_cell_with_a_rule_warning_is_rule_rejected() -> None:
    result = coverage("IS", "annual", (warning("cost_of_revenue", "FY2022"),))

    assert result.causes[("cost_of_revenue", "FY2022")] == "rule_rejected"
    assert result.causes[("cost_of_revenue", "FY2021")] == "not_reported"  # another period
    assert result.causes[("rnd", "FY2022")] == "not_reported"  # another code


def test_a_warning_without_a_value_also_makes_the_cell_rule_rejected() -> None:
    refused = RuleWarning("cash_rollforward", "cost_of_revenue", "FY2022", None, "mixed filings")

    assert (
        coverage("IS", "annual", (refused,)).causes[("cost_of_revenue", "FY2022")]
        == "rule_rejected"
    )


def test_q4_follows_a_rejection_in_the_year() -> None:
    result = coverage("IS", "quarterly", (warning("cost_of_revenue", "FY2022"),))

    assert result.causes[("cost_of_revenue", "FY2022Q4")] == "rule_rejected"
    assert result.causes[("cost_of_revenue", "FY2021Q4")] == "not_reported"


def test_a_value_hides_its_warning() -> None:
    result = coverage("IS", "annual", (warning("revenue", "FY2022"),))

    assert ("revenue", "FY2022") not in result.causes


def test_the_cause_counts_and_provenance_counts_add_up_to_the_cells() -> None:
    for statement in ("IS", "BS"):
        for freq in ("annual", "quarterly"):
            result = coverage(statement, freq)

            assert result.cells == result.filled + sum(result.empty_by_cause.values())
            assert result.filled == sum(result.by_provenance.values())
            assert set(result.by_provenance) == set(PROVENANCES)


def test_the_cells_are_the_non_residual_items_times_the_periods() -> None:
    annual = coverage("IS", "annual")
    quarterly = coverage("IS", "quarterly")

    # revenue, cost_of_revenue, gross_profit, rnd, ebit; the residual is left out
    assert annual.cells == 5 * 3
    assert quarterly.cells == 5 * 12
    assert (annual.statement, annual.freq) == ("IS", "annual")


def test_the_support_lines_of_an_identity_are_not_cells() -> None:
    assert coverage("BS", "annual").cells == 1 * 3  # cash only: shares_issued is optional


def test_provenance_counts_separate_reported_from_derived() -> None:
    result = coverage("IS", "annual")

    assert result.by_provenance["reported"] == 3 + 1  # revenue in 3 years, cost_of_revenue in 2023
    assert result.by_provenance["derived"] == 1  # gross_profit FY2023
    assert result.by_provenance["zero_inferred"] == 0


def test_imported_cells_are_counted_as_their_own_provenance() -> None:
    base = table("IS", "annual")
    revenue = next(r for r in base.rows if r.code == "revenue")
    imported = replace(revenue, provenance=["imported", "reported", "reported"])
    swapped = replace(base, rows=[imported if r.code == "revenue" else r for r in base.rows])

    result = table_coverage(swapped, ITEMS, MAPPED, ())

    assert result.by_provenance["imported"] == 1
    assert result.by_provenance["reported"] == 2 + 1  # revenue in two years, cost_of_revenue
    assert result.filled == sum(result.by_provenance.values())


def test_the_fraction_leaves_out_periods_with_no_filing_data() -> None:
    result = coverage("BS", "annual")

    assert result.empty_by_cause["no_filing_data"] == 2
    assert result.fraction == Decimal(1)  # cash FY2023, the one applicable cell


def test_the_fraction_is_none_when_there_is_nothing_to_cover() -> None:
    empty = StatementTable("IS", "annual", [], [], None, [])

    result = table_coverage(empty, ITEMS, MAPPED, ())

    assert (result.cells, result.filled, result.fraction) == (0, 0, None)


def test_the_fraction_is_filled_over_the_applicable_cells() -> None:
    result = coverage("IS", "annual")

    assert result.fraction == Decimal("0.333333")  # 5 of 15, to six places
    assert result.filled == 5


# --- the four recorded companies -------------------------------------------------------------


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_every_empty_cell_of_a_fixture_has_a_cause_and_the_counts_add_up(
    ticker: str, freq: str
) -> None:
    pipeline = run_pipeline(ticker)
    mapped = set(pipeline.mappings["canonical_code"])
    tables = pipeline.annual if freq == "annual" else pipeline.quarterly

    for statement, statement_table in tables.items():
        result = table_coverage(
            statement_table,
            pipeline.items,
            mapped,
            statement_table.rule_warnings,
            annual=pipeline.annual[statement],
        )

        assert result.cells > 0
        assert result.cells == result.filled + sum(result.empty_by_cause.values())
        assert len(result.causes) == sum(result.empty_by_cause.values())
        assert result.fraction is not None and Decimal(0) < result.fraction <= Decimal(1), statement
        assert result.fraction_applicable is not None
        assert result.fraction <= result.fraction_applicable <= Decimal(1), statement


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_annual_causes_list_exactly_the_missing_items(ticker: str) -> None:
    """Data gaps' old "missing items" and the new causes describe the same empty cells."""
    from bedrock.mapping.gaps import missing_items

    pipeline = run_pipeline(ticker)
    mapped = set(pipeline.mappings["canonical_code"])
    listed = {
        (m.code, period)
        for m in missing_items(pipeline.annual, pipeline.items)
        for period in m.missing_periods
    }

    causes = {
        key
        for statement, t in pipeline.annual.items()
        for key in table_coverage(t, pipeline.items, mapped, t.rule_warnings).causes
    }

    assert causes == listed


def test_deere_has_no_operating_income_by_design() -> None:
    pipeline = run_pipeline("DE")
    mapped = set(pipeline.mappings["canonical_code"])
    income = pipeline.annual["IS"]

    causes = table_coverage(income, pipeline.items, mapped, income.rule_warnings).causes

    periods = [p.key for p in income.periods]
    assert {causes[("operating_income", key)] for key in periods} == {"structural"}


def test_apple_has_inferred_zeros_and_approximated_q4_cells() -> None:
    pipeline = run_pipeline("AAPL")
    mapped = set(pipeline.mappings["canonical_code"])

    def provenance(tables: dict[str, StatementTable]) -> dict[str, int]:
        totals = dict.fromkeys(PROVENANCES, 0)
        for t in tables.values():
            for name, count in table_coverage(
                t, pipeline.items, mapped, t.rule_warnings
            ).by_provenance.items():
                totals[name] += count
        return totals

    assert provenance(pipeline.annual)["zero_inferred"] > 0  # NCI
    assert provenance(pipeline.quarterly)["approximated"] > 0  # Q4 shares and EPS


def test_apples_refused_cash_roll_forward_cells_are_rule_rejected() -> None:
    pipeline = run_pipeline("AAPL")
    mapped = set(pipeline.mappings["canonical_code"])
    cash_flow = pipeline.annual["CF"]
    assert cash_flow.rule_warnings  # S7: three FX periods are refused

    causes = table_coverage(cash_flow, pipeline.items, mapped, cash_flow.rule_warnings).causes

    rejected = {key for key, cause in causes.items() if cause == "rule_rejected"}
    warned = {(w.code, w.period_key) for w in cash_flow.rule_warnings}
    assert rejected and rejected <= warned


# --- M7b S2: anchors, not_applicable, annual_only (docs/erd/data-coverage.md) ----------------

LEASE = replace(item("lease", "BS", kind="instant"), starts_with_standard=True)
S2_ITEMS = [
    item("revenue"),
    item("rnd"),
    item("total_assets", "BS", kind="instant"),
    item("cash", "BS", kind="instant"),
    LEASE,
]
S2_MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("rnd", "ResearchAndDevelopmentExpense", 0),
    ("total_assets", "Assets", 0),
    ("cash", "Cash", 0),
    ("lease", "OperatingLeaseRightOfUseAsset", 0),
)
S2_MAPPED = set(S2_MAPS["canonical_code"])
ALL_FOUR = (1, 1, 1, 1)


def s2_table(statement: str, freq: str, *, lease: bool = True) -> StatementTable:
    """FY2021-FY2024. The balance sheet has cash every year and total assets from FY2022, so
    FY2021 has rows but no anchor; the lease line starts in Q3 FY2023 and stops after FY2023."""
    raw = (
        flow_facts("Revenues", {y: ALL_FOUR for y in (2021, 2022, 2023, 2024)})
        + flow_facts("ResearchAndDevelopmentExpense", {2023: ALL_FOUR})
        + instant_facts("Cash", {y: ALL_FOUR for y in (2021, 2022, 2023, 2024)})
        + instant_facts("Assets", {y: ALL_FOUR for y in (2022, 2023, 2024)})
        + (
            instant_facts("OperatingLeaseRightOfUseAsset", {2023: (None, None, 1, 1)})
            if lease
            else []
        )
    )
    canonical = map_facts(select_vintage(facts(raw)), S2_MAPS, S2_ITEMS)
    return build_statement(canonical, S2_ITEMS, statement, freq)  # type: ignore[arg-type]


def blank(table: StatementTable, code: str, keys: set[str]) -> StatementTable:
    """`table` with the cells of `code` in the periods `keys` emptied."""
    rows = []
    for row in table.rows:
        if row.code == code:
            at = [n for n, p in enumerate(table.periods) if p.key in keys]
            values = [None if n in at else v for n, v in enumerate(row.values)]
            provenance = [None if n in at else p for n, p in enumerate(row.provenance)]
            row = replace(row, values=values, provenance=provenance)
        rows.append(row)
    return replace(table, rows=rows)


def test_a_balance_sheet_period_with_rows_but_no_anchor_is_no_filing_data() -> None:
    result = table_coverage(s2_table("BS", "annual"), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("total_assets", "FY2021")] == "no_filing_data"
    assert result.causes[("lease", "FY2021")] == "no_filing_data"  # before not_applicable
    assert ("cash", "FY2021") not in result.causes  # a value is still a value
    assert result.empty_by_cause["no_filing_data"] == 2


def test_the_statement_anchors() -> None:
    assert STATEMENT_ANCHORS == {
        "IS": ("net_income", "net_income_common", "revenue"),
        "BS": ("total_assets", "total_liabilities_and_equity"),
        "CF": ("cfo", "net_change_in_cash"),
    }


def test_a_line_a_standard_introduced_is_not_applicable_before_its_first_value() -> None:
    result = table_coverage(s2_table("BS", "annual"), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("lease", "FY2022")] == "not_applicable"
    assert ("lease", "FY2023") not in result.causes
    assert result.causes[("lease", "FY2024")] == "not_reported"  # after the first value


def test_not_applicable_follows_the_first_value_of_each_table() -> None:
    result = table_coverage(s2_table("BS", "quarterly"), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("lease", "FY2023Q2")] == "not_applicable"
    assert ("lease", "FY2023Q3") not in result.causes
    assert result.causes[("lease", "FY2024Q1")] == "not_reported"


def test_a_company_without_any_lease_value_has_a_lease_line_that_is_not_applicable() -> None:
    # M7b S5 (user, 2026-11-14): a line the company never reports is not applicable
    result = table_coverage(s2_table("BS", "annual", lease=False), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("lease", "FY2022")] == "not_applicable"
    assert result.causes[("lease", "FY2021")] == "no_filing_data"  # still first


# --- M7b S5 (user, 2026-11-14): a line with no value in any period is not applicable, unless the
# item is `required` (a line every company has) ------------------------------------------------

ALL_YEARS = {"FY2021", "FY2022", "FY2023", "FY2024"}


def test_a_line_never_reported_in_any_period_is_not_applicable() -> None:
    annual = blank(s2_table("IS", "annual"), "rnd", ALL_YEARS)

    result = table_coverage(annual, S2_ITEMS, S2_MAPPED, ())

    assert {result.causes[("rnd", key)] for key in ALL_YEARS} == {"not_applicable"}
    assert result.fraction_applicable == Decimal("1.000000")  # revenue, every year
    assert result.fraction == Decimal("0.500000")  # strict still counts the empty line


def test_a_required_line_never_reported_is_still_a_gap() -> None:
    items = [replace(i, required=True) if i.code == "rnd" else i for i in S2_ITEMS]
    annual = blank(s2_table("IS", "annual"), "rnd", ALL_YEARS)

    result = table_coverage(annual, items, S2_MAPPED, ())

    assert {result.causes[("rnd", key)] for key in ALL_YEARS} == {"not_reported"}


def test_a_line_whose_only_values_are_inferred_zeros_is_still_never_reported() -> None:
    # M7b S7: R9 proves a 0 where a 10-K face has no line; that is no report of the line, so the
    # line's other empty cells stay not applicable instead of turning into gaps
    annual = blank(s2_table("IS", "annual"), "rnd", ALL_YEARS - {"FY2023"})
    rows = [
        replace(
            r,
            values=[Decimal(0) if v is not None else None for v in r.values],
            provenance=["zero_inferred" if v is not None else None for v in r.values],
        )
        if r.code == "rnd"
        else r
        for r in annual.rows
    ]

    result = table_coverage(replace(annual, rows=rows), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("rnd", "FY2022")] == "not_applicable"
    assert ("rnd", "FY2023") not in result.causes  # the inferred zero is a filled cell


def test_a_line_with_one_value_keeps_its_gaps() -> None:
    result = table_coverage(s2_table("IS", "annual"), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("rnd", "FY2022")] == "not_reported"  # rnd has FY2023


def test_a_quarterly_line_with_annual_values_is_not_never_reported() -> None:
    annual = s2_table("IS", "annual")
    quarterly = s2_table("IS", "quarterly")
    keys = {p.key for p in quarterly.periods}
    quarterly = blank(quarterly, "rnd", keys)

    with_annual = table_coverage(quarterly, S2_ITEMS, S2_MAPPED, (), annual=annual)
    never = table_coverage(
        quarterly, S2_ITEMS, S2_MAPPED, (), annual=blank(annual, "rnd", ALL_YEARS)
    )

    assert with_annual.causes[("rnd", "FY2023Q1")] == "annual_only"
    assert with_annual.causes[("rnd", "FY2022Q1")] == "not_reported"
    assert {never.causes[("rnd", key)] for key in keys} == {"not_applicable"}


def test_a_never_reported_line_keeps_a_rule_rejection() -> None:
    annual = blank(s2_table("IS", "annual"), "rnd", ALL_YEARS)

    result = table_coverage(annual, S2_ITEMS, S2_MAPPED, (warning("rnd", "FY2022"),))

    assert result.causes[("rnd", "FY2022")] == "rule_rejected"
    assert result.causes[("rnd", "FY2021")] == "not_applicable"


def test_a_line_without_the_flag_is_never_not_applicable() -> None:
    result = table_coverage(s2_table("IS", "annual"), S2_ITEMS, S2_MAPPED, ())

    assert result.causes[("rnd", "FY2022")] == "not_reported"  # rnd starts in FY2023, no flag


def test_a_year_with_an_annual_value_and_no_quarter_is_annual_only() -> None:
    annual = s2_table("IS", "annual")
    quarters = {f"FY2023Q{n}" for n in (1, 2, 3, 4)}
    quarterly = blank(s2_table("IS", "quarterly"), "rnd", quarters)

    result = table_coverage(quarterly, S2_ITEMS, S2_MAPPED, (), annual=annual)

    assert {result.causes[("rnd", key)] for key in quarters} == {"annual_only"}
    assert result.causes[("rnd", "FY2022Q1")] == "not_reported"  # no annual value that year


def test_a_year_with_one_quarter_is_not_annual_only() -> None:
    annual = s2_table("IS", "annual")
    quarterly = blank(s2_table("IS", "quarterly"), "rnd", {"FY2023Q2", "FY2023Q3", "FY2023Q4"})

    result = table_coverage(quarterly, S2_ITEMS, S2_MAPPED, (), annual=annual)

    assert result.causes[("rnd", "FY2023Q2")] == "not_reported"
    assert result.empty_by_cause["annual_only"] == 0


def test_annual_only_needs_the_annual_table() -> None:
    quarterly = blank(s2_table("IS", "quarterly"), "rnd", {f"FY2023Q{n}" for n in (1, 2, 3, 4)})
    # required: without the annual table the quarterly row alone would read as never reported
    items = [replace(i, required=True) if i.code == "rnd" else i for i in S2_ITEMS]

    result = table_coverage(quarterly, items, S2_MAPPED, ())

    assert result.empty_by_cause["annual_only"] == 0
    assert result.causes[("rnd", "FY2023Q1")] == "not_reported"


def test_a_rule_warning_comes_before_annual_only() -> None:
    annual = s2_table("IS", "annual")
    quarterly = blank(s2_table("IS", "quarterly"), "rnd", {f"FY2023Q{n}" for n in (1, 2, 3, 4)})

    result = table_coverage(
        quarterly, S2_ITEMS, S2_MAPPED, (warning("rnd", "FY2023Q1"),), annual=annual
    )

    assert result.causes[("rnd", "FY2023Q1")] == "rule_rejected"
    assert result.causes[("rnd", "FY2023Q2")] == "annual_only"


def test_an_annual_table_has_no_annual_only_cell() -> None:
    annual = blank(s2_table("IS", "annual"), "rnd", {"FY2023"})

    result = table_coverage(annual, S2_ITEMS, S2_MAPPED, (), annual=annual)

    assert result.empty_by_cause["annual_only"] == 0


def test_every_cause_is_counted_in_cause_order() -> None:
    assert CAUSES == (
        "no_filing_data",
        "not_applicable",
        "included_in",
        "structural",
        "rule_rejected",
        "annual_only",
        "extension_unclassified",
        "not_reported",
    )
    result = table_coverage(s2_table("BS", "annual"), S2_ITEMS, S2_MAPPED, ())
    assert list(result.empty_by_cause) == list(CAUSES)


def test_the_applicable_fraction_also_leaves_out_cells_that_cannot_exist() -> None:
    result = table_coverage(s2_table("BS", "annual"), S2_ITEMS, S2_MAPPED, ())

    # 3 lines x 4 years; filled: total_assets 3, cash 4, lease 1; no_filing_data 2 (FY2021)
    assert (result.cells, result.filled) == (12, 8)
    assert result.fraction == Decimal("0.800000")  # 8 / (12 - 2)
    assert result.fraction_applicable == Decimal("0.888889")  # 8 / (12 - 2 - 1)


def test_the_applicable_fraction_is_none_when_nothing_is_applicable() -> None:
    empty = StatementTable("IS", "annual", [], [], None, [])

    assert table_coverage(empty, S2_ITEMS, S2_MAPPED, ()).fraction_applicable is None


@pytest.mark.parametrize("seed", range(30))
def test_the_applicable_fraction_is_never_below_the_strict_one(seed: int) -> None:
    """A seeded property (hypothesis is not installed): blank random cells of random tables."""
    import random

    rng = random.Random(seed)
    statement, freq = rng.choice([("IS", "annual"), ("BS", "annual"), ("BS", "quarterly")])
    table = s2_table(statement, freq, lease=rng.random() < 0.7)
    keys = {p.key for p in table.periods}
    for code in ("revenue", "rnd", "total_assets", "cash", "lease"):
        table = blank(table, code, {k for k in keys if rng.random() < 0.3})

    result = table_coverage(table, S2_ITEMS, S2_MAPPED, ())

    assert result.cells == result.filled + sum(result.empty_by_cause.values())
    if result.fraction is not None:
        assert result.fraction_applicable is not None
        assert result.fraction <= result.fraction_applicable <= Decimal(1)


# The strict fraction of every table of the four companies, and its no_filing_data cells, pinned.
# It has moved four times (docs/erd/data-coverage.md, the "What S<n> built" blocks): S2's anchor
# rule (the balance sheet's first year, comparatives only, became no_filing_data); S4's combined
# fill of Deere's `change_payables`; S5's seven new rows, which add their cells to every table
# of their statement while a company that never reports one leaves all of them empty; and S7's
# structure rules and extension lines (face sums, inferred zeros, MSFT's and DE's extension tags),
# which only fill empty cells. The cells of the rows that existed before do not change
# (`test_mapping_baseline_guard.py`).
STRICT = {  # (ticker, statement, freq): (strict fraction, no_filing_data cells)
    ("AAPL", "IS", "annual"): ("0.913158", 0),
    ("AAPL", "BS", "annual"): ("0.817485", 32),
    ("AAPL", "CF", "annual"): ("0.908467", 0),
    ("AAPL", "IS", "quarterly"): ("0.873239", 0),
    ("AAPL", "BS", "quarterly"): ("0.788013", 70),
    ("AAPL", "CF", "quarterly"): ("0.889161", 0),
    ("MSFT", "IS", "annual"): ("0.921053", 0),
    ("MSFT", "BS", "annual"): ("0.890076", 29),
    ("MSFT", "CF", "annual"): ("0.867277", 0),
    ("MSFT", "IS", "quarterly"): ("0.900694", 0),
    ("MSFT", "BS", "quarterly"): ("0.880208", 96),
    ("MSFT", "CF", "quarterly"): ("0.770531", 0),
    ("COST", "IS", "annual"): ("0.842105", 0),
    ("COST", "BS", "annual"): ("0.770468", 0),
    ("COST", "CF", "annual"): ("0.876430", 0),
    ("COST", "IS", "quarterly"): ("0.832639", 0),
    ("COST", "BS", "quarterly"): ("0.750704", 105),
    ("COST", "CF", "quarterly"): ("0.816425", 0),
    ("DE", "IS", "annual"): ("0.763158", 0),
    ("DE", "BS", "annual"): ("0.605828", 32),
    ("DE", "CF", "annual"): ("0.979405", 0),
    ("DE", "IS", "quarterly"): ("0.752239", 0),
    ("DE", "BS", "quarterly"): ("0.578358", 0),
    ("DE", "CF", "quarterly"): ("0.878650", 0),
}


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_strict_fraction_of_every_table_is_pinned(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    mapped = set(pipeline.mappings["canonical_code"])

    for freq, tables in (("annual", pipeline.annual), ("quarterly", pipeline.quarterly)):
        for statement, t in tables.items():
            result = table_coverage(
                t, pipeline.items, mapped, t.rule_warnings, annual=pipeline.annual[statement]
            )
            now, no_data = STRICT[(ticker, statement, freq)]
            assert (result.fraction, result.empty_by_cause["no_filing_data"]) == (
                Decimal(now),
                no_data,
            ), (ticker, statement, freq)


def test_the_fixtures_have_lease_years_before_asc_842_and_annual_only_quarters() -> None:
    pipeline = run_pipeline("AAPL")
    mapped = set(pipeline.mappings["canonical_code"])
    bs, cf = pipeline.annual["BS"], pipeline.quarterly["CF"]

    lease = table_coverage(bs, pipeline.items, mapped, bs.rule_warnings).causes
    quarters = table_coverage(
        cf, pipeline.items, mapped, cf.rule_warnings, annual=pipeline.annual["CF"]
    )

    assert {code for (code, _), cause in lease.items() if cause == "not_applicable"} == {
        "operating_lease_rou",
        "operating_lease_liabilities_noncurrent",
        "pension_liabilities",  # M7b S5: Apple reports no defined benefit plan line in any year
    }
    assert quarters.empty_by_cause["annual_only"] > 0


# --- M7b S4: included_in ------------------------------------------------------------------


def combined_items() -> list[CanonicalItemDef]:
    from tests.test_combined_lines import BS_ITEMS

    return [*BS_ITEMS, item("total_assets", "BS", kind="instant")]  # the statement's anchor


def combined_table() -> StatementTable:
    from tests.test_combined_lines import COMBINED, balances

    raw = balances(
        Assets=(200, 200, 200, 200),
        LiabilitiesCurrent=(100, 100, 100, 100),
        **{COMBINED: (60, 61, 62, 63)},
    )
    maps = pd.concat([test_combined_lines.BS_MAP, mappings(("total_assets", "Assets", 0))])
    canonical = map_facts(select_vintage(facts(raw)), maps, combined_items())
    return build_statement(canonical, combined_items(), "BS", "annual")


def test_a_covered_cell_is_included_in_and_out_of_the_applicable_cells() -> None:
    mapped = {
        "total_assets",
        "total_current_liabilities",
        "accounts_payable",
        "accrued_liabilities",
    }
    result = table_coverage(combined_table(), combined_items(), mapped, ())

    assert result.causes[("accrued_liabilities", "FY2023")] == "included_in"
    assert result.empty_by_cause["included_in"] == 1
    # strict: assets, total and payables filled, accrued empty; applicable leaves accrued out
    assert result.fraction == Decimal("0.75")
    assert result.fraction_applicable == Decimal(1)


def test_included_in_comes_before_structural() -> None:
    # even with no concept mapped for it, a covered cell is included in its carrier
    result = table_coverage(combined_table(), combined_items(), {"accounts_payable"}, ())

    assert result.causes[("accrued_liabilities", "FY2023")] == "included_in"


# --- M7b S7: extension_unclassified ---------------------------------------------------------


def unclassified_table() -> StatementTable:
    from bedrock.statements.rules import Rules
    from bedrock.statements.structure import FaceLines
    from tests import test_structure_rules as s

    weird = s.line(f"K-{s.FY}", "BS", "x:Weird", "LiabilitiesCurrent")
    raw = [*s.base_facts(), *s.debt_facts(CommercialPaper=3 * s.B, LongTermDebtCurrent=2 * s.B)]
    line_facts = [*raw, *[{**r, "taxonomy": "x"} for r in s.debt_facts(Weird=s.B)]]
    face = FaceLines(
        s.lines_frame(s.balance_sheet_lines(f"K-{s.FY}", "10-K", weird)), facts(line_facts), s.MAPS
    )
    canonical = map_facts(select_vintage(facts(raw)), s.MAPS, s.ITEMS)
    return build_statement(canonical, s.ITEMS, "BS", "annual", rules=Rules(filing_lines=face))


def required_items() -> list[CanonicalItemDef]:
    """The structure-rule items with the two debt-side lines `required`, so that a line the
    company never reports stays a gap (`not_applicable` comes first otherwise)."""
    from tests import test_structure_rules as s

    wanted = {"short_term_debt", "accrued_liabilities"}
    return [replace(i, required=True) if i.code in wanted else i for i in s.ITEMS]


def test_an_empty_cell_whose_block_has_an_unclassified_line_is_extension_unclassified() -> None:
    from tests import test_structure_rules as s

    table = unclassified_table()
    row = next(r for r in table.rows if r.code == "short_term_debt")
    result = table_coverage(table, required_items(), {i.code for i in s.ITEMS}, ())

    assert row.unclassified[
        table.periods.index(next(p for p in table.periods if p.key == "FY2023"))
    ] == ("x:Weird",)
    assert result.causes[("short_term_debt", "FY2023")] == "extension_unclassified"
    assert result.causes[("accrued_liabilities", "FY2023")] == "extension_unclassified"
    assert result.empty_by_cause["extension_unclassified"] == 2
    # a gap like any other: it stays in the applicable denominator
    assert result.fraction == result.fraction_applicable


def test_structural_comes_before_extension_unclassified() -> None:
    from tests import test_structure_rules as s

    mapped = {i.code for i in s.ITEMS} - {"accrued_liabilities"}
    result = table_coverage(unclassified_table(), required_items(), mapped, ())

    assert result.causes[("accrued_liabilities", "FY2023")] == "structural"
