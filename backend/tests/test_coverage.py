"""R6: why a cell is empty, and how complete each statement is (erd/data.md, "R6")."""

from decimal import Decimal

import pytest

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cell_types import RuleWarning
from bedrock.statements.coverage import PROVENANCES, table_coverage
from tests.engine_data import facts, flow_facts, instant_facts, item, mappings
from tests.statements_pipeline import run_pipeline
from tests.test_statements_golden import TICKERS

ITEMS = [
    item("revenue"),
    item("cost_of_revenue", parent="gross_profit"),
    item("gross_profit", derive="revenue - cost_of_revenue"),
    item("rnd"),
    item("ebit"),  # nothing maps it and it has no formula: the company excludes every concept
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
            statement_table, pipeline.items, mapped, statement_table.rule_warnings
        )

        assert result.cells > 0
        assert result.cells == result.filled + sum(result.empty_by_cause.values())
        assert len(result.causes) == sum(result.empty_by_cause.values())
        assert result.fraction is not None and Decimal(0) < result.fraction <= Decimal(1), statement


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
