from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.cells import DerivationInput
from bedrock.statements.explain import CellExplanation, explain_cell
from tests.engine_data import fact, facts, flow_facts, item, mappings

REVENUE = {2022: (100, 110, 120, 130), 2023: (150, 160, 170, 180)}
ITEMS = [
    item("revenue"),
    item("cost_of_revenue", parent="gross_profit"),
    item("gross_profit", derive="revenue - cost_of_revenue"),
    item("capex", "CF", sign=-1),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("capex", "PaymentsToAcquirePPE", 0),
)
RESTATED_FILED = date(2024, 8, 20)


def raw_facts() -> pd.DataFrame:
    rows = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2023: (50, 50, 50, 50)})
    rows += flow_facts("PaymentsToAcquirePPE", {2023: (5, 5, 5, 5)})
    # the FY2023 10-K figure is restated a year later
    rows.append(
        fact(
            "Revenues",
            date(2022, 7, 1),
            date(2023, 6, 30),
            665,
            accession="K-2024",
            filed=RESTATED_FILED,
        )
    )
    return facts(rows)


def explain(code: str, fiscal_year: int, fiscal_period: str) -> CellExplanation:
    vintages = raw_facts()
    canonical = map_facts(select_vintage(vintages), MAPS, ITEMS)
    return explain_cell(canonical, vintages, ITEMS, code, fiscal_year, fiscal_period)


def test_a_reported_cell_names_its_source_filing_and_every_vintage() -> None:
    cell = explain("revenue", 2023, "FY")

    assert (cell.code, cell.label, cell.fiscal_year, cell.fiscal_period) == (
        "revenue",
        "Revenue",
        2023,
        "FY",
    )
    assert cell.value == 665 and cell.provenance == "reported"
    assert cell.derivation is None
    assert cell.source is not None
    assert (cell.source.taxonomy, cell.source.concept, cell.source.unit) == (
        "us-gaap",
        "Revenues",
        "USD",
    )
    assert cell.filing is not None
    assert (cell.filing.accession_no, cell.filing.form, cell.filing.filed_at) == (
        "K-2024",
        "10-K",
        RESTATED_FILED,
    )
    assert [(v.value, v.accession_no, v.form) for v in cell.vintages] == [
        (660, "K-2023", "10-K"),
        (665, "K-2024", "10-K"),
    ]


def test_a_reported_quarter_cites_its_10q() -> None:
    cell = explain("revenue", 2023, "Q2")

    assert cell.value == 160 and cell.provenance == "reported"
    assert cell.filing is not None and (cell.filing.accession_no, cell.filing.form) == (
        "Q2-2023",
        "10-Q",
    )
    assert [v.value for v in cell.vintages] == [160]


def test_a_derived_q4_shows_its_formula_and_inputs() -> None:
    cell = explain("revenue", 2023, "Q4")

    assert cell.value == 665 - 480 and cell.provenance == "derived"
    assert cell.source is None and cell.filing is None and cell.vintages == []
    assert cell.derivation is not None
    assert cell.derivation.formula == "FY - YTD Q3"
    assert cell.derivation.inputs == (
        DerivationInput("revenue", "FY", Decimal(665)),
        DerivationInput("revenue", "YTD Q3", Decimal(480)),
    )


def test_a_formula_cell_lists_its_operands() -> None:
    cell = explain("gross_profit", 2023, "FY")

    assert cell.value == 665 - 200 and cell.provenance == "derived"
    assert cell.derivation is not None
    assert cell.derivation.formula == "revenue - cost_of_revenue"
    assert cell.derivation.inputs == (
        DerivationInput("revenue", "FY", Decimal(665)),
        DerivationInput("cost_of_revenue", "FY", Decimal(200)),
    )


def test_vintages_are_shown_with_the_sign_the_cell_uses() -> None:
    cell = explain("capex", 2023, "FY")

    assert cell.value == -20
    assert [v.value for v in cell.vintages] == [-20]


def test_a_cell_without_a_value_has_no_provenance() -> None:
    cell = explain("gross_profit", 2022, "FY")  # no cost of revenue before FY2023

    assert cell.value is None and cell.provenance is None
    assert cell.source is None and cell.derivation is None and cell.vintages == []


@pytest.mark.parametrize(
    "code, fiscal_year, fiscal_period",
    [
        ("ghost", 2023, "FY"),
        ("revenue", 1999, "FY"),
        ("revenue", 2023, "Q5"),
        ("revenue", 2023, "TTM"),
    ],
)
def test_an_unknown_code_or_period_is_a_key_error(
    code: str, fiscal_year: int, fiscal_period: str
) -> None:
    with pytest.raises(KeyError):
        explain(code, fiscal_year, fiscal_period)
