from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import balance_snapshot, select_vintage
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


def test_a_q4_whose_year_to_date_disagrees_with_the_quarters_says_so() -> None:
    # The 10-Q's nine-month figure was restated to 470, but Q1..Q3 as reported add up to 480:
    # Q4 is the year less the quarters as displayed, and the formula names them.
    vintages = pd.concat(
        [
            raw_facts(),
            facts(
                [
                    fact(
                        "Revenues",
                        date(2022, 7, 1),
                        date(2023, 3, 31),
                        470,
                        accession="Q3-2023-A",
                        form="10-Q/A",
                        filed=date(2023, 6, 1),
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    canonical = map_facts(select_vintage(vintages), MAPS, ITEMS)

    cell = explain_cell(canonical, vintages, ITEMS, "revenue", 2023, "Q4")

    assert cell.value == 665 - 480
    assert cell.derivation is not None
    assert cell.derivation.formula == "FY - Q1 - Q2 - Q3"
    assert cell.derivation.inputs == (
        DerivationInput("revenue", "FY", Decimal(665)),
        DerivationInput("revenue", "Q1", Decimal(150)),
        DerivationInput("revenue", "Q2", Decimal(160)),
        DerivationInput("revenue", "Q3", Decimal(170)),
    )


# --- Summed concepts: the vintages are the sum as of each filing --------------------------------

DEBT_ITEMS = [item("revenue"), item("short_term_debt", "BS", kind="instant", sign=1)]
DEBT_MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("short_term_debt", "CommercialPaper", 0),
    ("short_term_debt", "LongTermDebtCurrent", 0),
    ("short_term_debt", "LongTermDebtCurrent", 1),
)
YEAR_END = date(2023, 6, 30)


def explain_debt(rows: list[dict[str, object]]) -> CellExplanation:
    vintages = facts(
        flow_facts("Revenues", {2023: (1, 1, 1, 1)}) + rows
    )  # the revenue sets the calendar
    canonical = map_facts(select_vintage(vintages), DEBT_MAPS, DEBT_ITEMS)
    return explain_cell(canonical, vintages, DEBT_ITEMS, "short_term_debt", 2023, "FY")


def debt_fact(concept: str, value: int, accession: str, filed: date) -> dict[str, object]:
    return fact(concept, None, YEAR_END, value, accession=accession, filed=filed)


def test_a_summed_cell_names_every_member_and_its_vintages_add_them_per_filing() -> None:
    cell = explain_debt(
        [
            debt_fact("CommercialPaper", 100, "K-2023", date(2023, 8, 1)),
            debt_fact("LongTermDebtCurrent", 25, "K-2023", date(2023, 8, 1)),
            # the next 10-K restates the commercial paper only
            debt_fact("CommercialPaper", 90, "K-2024", date(2024, 8, 1)),
        ]
    )

    assert cell.value == 90 + 25
    assert cell.source is not None
    assert (cell.source.taxonomy, cell.source.concept) == (
        "us-gaap",
        "CommercialPaper + LongTermDebtCurrent",
    )
    # As of K-2024 the other member still stands at its K-2023 value, so the last vintage is the
    # value the cell shows.
    assert [(v.accession_no, v.value) for v in cell.vintages] == [
        ("K-2023", 125),
        ("K-2024", 115),
    ]


def test_a_summed_cells_vintages_skip_filings_before_the_anchor_existed() -> None:
    cell = explain_debt(
        [
            debt_fact("LongTermDebtCurrent", 25, "K-2023", date(2023, 8, 1)),
            debt_fact("CommercialPaper", 100, "K-2024", date(2024, 8, 1)),
        ]
    )

    assert cell.value == 125
    assert [(v.accession_no, v.value) for v in cell.vintages] == [("K-2024", 125)]


def test_vintages_of_a_summed_cell_use_the_sign_of_the_item() -> None:
    vintages = facts([fact("PaymentsA", *FY23_YEAR, 30), fact("PaymentsB", *FY23_YEAR, 12)])
    items = [item("capex", "CF", sign=-1)]
    maps = mappings(("capex", "PaymentsA", 0), ("capex", "PaymentsB", 0))
    canonical = map_facts(select_vintage(vintages), maps, items)

    cell = explain_cell(canonical, vintages, items, "capex", 2023, "FY")

    assert cell.value == -42
    assert [v.value for v in cell.vintages] == [-42]


FY23_YEAR = (date(2022, 7, 1), date(2023, 6, 30))


BS_ITEMS = [
    item("total_assets", "BS", kind="instant"),
    item("total_liabilities", "BS", kind="instant"),
    item("total_equity", "BS", kind="instant"),
]
BS_MAPS = mappings(
    ("total_assets", "Assets", 0),
    ("total_liabilities", "Liabilities", 0),
    ("total_equity", "StockholdersEquity", 0),
)


def test_a_balance_dated_off_the_period_end_keeps_the_vintages_of_its_own_date() -> None:
    """Deere dates its FY2015 balance sheet 31 Oct for the year ending 1 Nov, and a later 10-K
    restates total assets alone under 1 Nov. The cell shows the complete sheet's value, and its
    vintages list the filings of both dates, so the 10-K it cites is among them."""
    sheet_date, year_end = date(2023, 6, 29), date(2023, 6, 30)
    rows = flow_facts("Revenues", {2023: (1, 1, 1, 1)})  # defines the calendar
    for concept, value in (("Assets", 500), ("Liabilities", 300), ("StockholdersEquity", 200)):
        rows.append(
            fact(concept, None, sheet_date, value, accession="K-2023", filed=date(2023, 8, 20))
        )
    rows.append(fact("Assets", None, year_end, 499, accession="K-2025", filed=date(2025, 8, 20)))
    vintages = facts(rows)
    maps = pd.concat([MAPS, BS_MAPS], ignore_index=True)
    items = ITEMS + BS_ITEMS
    latest = select_vintage(vintages, snapshot=balance_snapshot(maps))
    cell = explain_cell(map_facts(latest, maps, items), vintages, items, "total_assets", 2023, "FY")

    assert cell.value == 500
    assert cell.filing is not None and cell.filing.accession_no == "K-2023"
    assert [(v.value, v.accession_no) for v in cell.vintages] == [(500, "K-2023"), (499, "K-2025")]
