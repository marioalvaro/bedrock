from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.gaps import MissingItem, UnmappedConcept, missing_items, unmapped_concepts
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import build_statement
from tests.engine_data import fact, facts, flow_facts, instant_facts, item, mappings

ITEMS = [
    item("revenue"),
    item("cost_of_revenue", parent="gross_profit"),
    item("gross_profit", derive="revenue - cost_of_revenue"),
    item("rnd"),
    item("other_operating_expenses", residual=True, derive="gross_profit - rnd"),
    item("cash", "BS", kind="instant"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("rnd", "ResearchAndDevelopmentExpense", 0),
    ("cash", "Cash", 0),
)
REVENUE = {2021: (1, 1, 1, 1), 2022: (1, 1, 1, 1), 2023: (1, 1, 1, 1)}


def tables(raw: list[dict[str, object]], freq: str = "annual"):  # type: ignore[no-untyped-def]
    canonical = map_facts(select_vintage(facts(raw)), MAPS, ITEMS)
    return {s: build_statement(canonical, ITEMS, s, freq) for s in ("IS", "BS")}  # type: ignore[arg-type]


def test_missing_items_lists_the_fiscal_years_with_no_value() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2023: (1, 1, 1, 1)})

    gaps = {g.code: g for g in missing_items(tables(raw), ITEMS)}

    assert gaps["cost_of_revenue"] == MissingItem(
        "cost_of_revenue", "Cost of revenue", "IS", ["FY2021", "FY2022"]
    )
    assert gaps["gross_profit"].missing_periods == [
        "FY2021",
        "FY2022",
    ]  # derive needs cost_of_revenue
    assert "revenue" not in gaps


def test_an_item_with_no_value_at_all_is_missing_in_every_year() -> None:
    raw = flow_facts("Revenues", REVENUE)

    gaps = {g.code: g for g in missing_items(tables(raw), ITEMS)}

    assert gaps["rnd"].missing_periods == ["FY2021", "FY2022", "FY2023"]


def test_residual_items_are_never_reported_missing() -> None:
    raw = flow_facts("Revenues", REVENUE)

    assert "other_operating_expenses" not in {g.code for g in missing_items(tables(raw), ITEMS)}


def test_balance_sheet_items_are_covered_too() -> None:
    raw = flow_facts("Revenues", REVENUE) + instant_facts("Cash", {2023: (1, 1, 1, 1)})

    gaps = {g.code: g for g in missing_items(tables(raw), ITEMS)}

    assert gaps["cash"].statement == "BS"
    assert gaps["cash"].missing_periods == ["FY2021", "FY2022"]


def test_only_fiscal_years_count_not_quarters() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2023: (1, 1, 1, 1)})

    gaps = {g.code: g for g in missing_items(tables(raw, freq="quarterly"), ITEMS)}

    assert gaps == {}


def test_a_complete_company_has_no_gaps() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", REVENUE)
    raw += flow_facts("ResearchAndDevelopmentExpense", REVENUE) + instant_facts("Cash", REVENUE)

    assert missing_items(tables(raw), ITEMS) == []


# --- unmapped concepts ---------------------------------------------------------------------

K23, K24 = date(2023, 8, 20), date(2024, 8, 20)


def unmapped_facts() -> pd.DataFrame:
    fy23 = (date(2022, 7, 1), date(2023, 6, 30))
    fy24 = (date(2023, 7, 1), date(2024, 6, 30))
    return facts(
        [
            # latest 10-K (FY2024): one mapped concept, two unmapped, one dei cover fact
            fact("Revenues", *fy24, 10, accession="K-24", filed=K24),
            fact("RestructuringCharges", *fy24, 7, accession="K-24", filed=K24),
            fact("RestructuringCharges", *fy23, 3, accession="K-24", filed=K24),
            fact("OddGain", None, fy24[1], 2, accession="K-24", filed=K24, taxonomy="aapl"),
            fact(
                "EntityCommonStockSharesOutstanding",
                None,
                date(2024, 8, 1),
                9,
                accession="K-24",
                filed=K24,
                taxonomy="dei",
                unit="shares",
            ),
            # the older 10-K and a 10-Q carry concepts the latest 10-K does not
            fact("OldCharge", *fy23, 5, accession="K-23", filed=K23),
            fact(
                "QuarterOnly",
                date(2024, 7, 1),
                date(2024, 9, 30),
                1,
                accession="Q1-25",
                form="10-Q",
                filed=date(2024, 11, 1),
            ),
        ]
    )


def test_unmapped_concepts_come_from_the_latest_10k_only() -> None:
    result = unmapped_concepts(unmapped_facts(), MAPS)

    assert [(u.taxonomy, u.concept) for u in result] == [
        ("aapl", "OddGain"),
        ("us-gaap", "RestructuringCharges"),
    ]


def test_an_unmapped_concept_reports_its_latest_value_end_and_fact_count() -> None:
    result = {u.concept: u for u in unmapped_concepts(unmapped_facts(), MAPS)}

    assert result["RestructuringCharges"] == UnmappedConcept(
        taxonomy="us-gaap",
        concept="RestructuringCharges",
        unit="USD",
        latest_value=Decimal(7),
        latest_period_end=date(2024, 6, 30),
        facts=2,
    )
    assert result["OddGain"].latest_value == 2 and result["OddGain"].facts == 1


def test_no_10k_means_nothing_to_report() -> None:
    quarterly = facts([fact("X", date(2024, 7, 1), date(2024, 9, 30), 1, form="10-Q")])

    assert unmapped_concepts(quarterly, MAPS) == []
    assert unmapped_concepts(facts([]), MAPS) == []


def test_a_10k_a_amendment_can_be_the_latest_annual_filing() -> None:
    amended = facts(
        [
            fact("Old", date(2022, 7, 1), date(2023, 6, 30), 1, accession="K-23", filed=K23),
            fact(
                "New",
                date(2022, 7, 1),
                date(2023, 6, 30),
                1,
                accession="KA-23",
                form="10-K/A",
                filed=K24,
            ),
        ]
    )

    assert [u.concept for u in unmapped_concepts(amended, MAPS)] == ["New"]
