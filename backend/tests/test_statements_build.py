from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import Row, StatementTable, build_statement
from tests.engine_data import Row as FactRow
from tests.engine_data import (
    fact,
    facts,
    flow_facts,
    fy_dates,
    instant_facts,
    item,
    mappings,
)

REVENUE = {2022: (100, 110, 120, 130), 2023: (150, 160, 170, 180)}

IS_ITEMS = [
    item("revenue"),
    item("cost_of_revenue", parent="gross_profit"),
    item("gross_profit", derive="revenue - cost_of_revenue"),
    item("eps_diluted", kind="average", unit="USD/shares"),
]
IS_MAP = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("gross_profit", "GrossProfit", 0),
    ("eps_diluted", "EarningsPerShareDiluted", 0),
)

BS_ITEMS = [
    item("cash", "BS", kind="instant", parent="total_current_assets"),
    item("receivables", "BS", kind="instant", parent="total_current_assets"),
    item(
        "other_current_assets",
        "BS",
        kind="instant",
        parent="total_current_assets",
        derive="total_current_assets - cash - receivables",
        residual=True,
    ),
    item("total_current_assets", "BS", kind="instant", parent="total_assets"),
    item("total_assets", "BS", kind="instant"),
    item(
        "total_liabilities",
        "BS",
        kind="instant",
        derive="total_liabilities_and_equity - total_equity",
    ),
    item("total_equity", "BS", kind="instant"),
    item("total_liabilities_and_equity", "BS", kind="instant"),
]
BS_MAP = mappings(
    ("cash", "Cash", 0),
    ("receivables", "Receivables", 0),
    ("total_current_assets", "AssetsCurrent", 0),
    ("total_assets", "Assets", 0),
    ("total_liabilities", "Liabilities", 0),
    ("total_equity", "Equity", 0),
    ("total_liabilities_and_equity", "LiabilitiesAndEquity", 0),
)

IS_BS_MAP = pd.concat([IS_MAP, BS_MAP], ignore_index=True)

CF_ITEMS = [
    item("cfo", "CF"),
    item("capex", "CF", sign=-1, parent="cfo"),
]
CF_MAP = mappings(("cfo", "NetCashFromOps", 0), ("capex", "PaymentsToAcquirePPE", 0))


def build(
    raw: Sequence[FactRow],
    items: list[CanonicalItemDef],
    maps: object,
    statement: str,
    freq: str,
    common_size_base: str = "total",
) -> StatementTable:
    canonical = map_facts(select_vintage(facts(raw)), maps, items)  # type: ignore[arg-type]
    return build_statement(canonical, items, statement, freq, common_size_base)  # type: ignore[arg-type]


def row(table: StatementTable, code: str) -> Row:
    (found,) = [r for r in table.rows if r.code == code]
    return found


def keys(table: StatementTable) -> list[str]:
    return [p.key for p in table.periods]


def revenue_table(freq: str, rows: Sequence[FactRow] | None = None) -> StatementTable:
    raw = rows if rows is not None else flow_facts("Revenues", REVENUE)
    return build(raw, IS_ITEMS, IS_MAP, "IS", freq)


# --- discrete periods ----------------------------------------------------------------------


def test_annual_values_are_the_12_month_facts() -> None:
    table = revenue_table("annual")

    assert keys(table) == ["FY2022", "FY2023"]
    assert row(table, "revenue").values == [460, 660]
    assert row(table, "revenue").provenance == ["reported", "reported"]


def test_three_month_facts_are_used_for_quarters_and_q4_is_derived() -> None:
    table = revenue_table("quarterly")

    revenue = row(table, "revenue")
    assert keys(table) == [f"FY{y}Q{n}" for y in (2022, 2023) for n in (1, 2, 3, 4)]
    assert revenue.values == [100, 110, 120, 130, 150, 160, 170, 180]
    assert revenue.provenance == (["reported"] * 3 + ["derived"]) * 2


def test_cash_flow_year_to_date_facts_are_differenced_and_marked_derived() -> None:
    raw = flow_facts("NetCashFromOps", {2023: (10, 12, 14, 16)}, ytd_only=True)

    table = build(raw, CF_ITEMS, CF_MAP, "CF", "quarterly")

    cfo = row(table, "cfo")
    assert cfo.values == [10, 12, 14, 16]
    assert cfo.provenance == ["reported", "derived", "derived", "derived"]


def test_q4_is_fy_minus_the_displayed_quarters_even_when_ytd_q3_disagrees() -> None:
    raw = flow_facts("Revenues", {2023: (100, 110, 120, 130)})
    # make the year-to-date Q3 fact disagree with the three discrete quarters (a later restatement)
    ytd_q3 = next(
        r
        for r in raw
        if r["period_end"] == date(2023, 3, 31) and r["period_start"] == date(2022, 7, 1)
    )
    ytd_q3["value"] = Decimal(329)

    values = row(revenue_table("quarterly", raw), "revenue").values

    assert values[:4] == [100, 110, 120, 460 - 330]  # not 460 - 329
    assert sum(v for v in values[:4] if v is not None) == 460  # the quarters always add up


def test_q4_falls_back_to_fy_minus_ytd_of_q3_when_a_quarter_cannot_be_derived() -> None:
    # No 10-Q reports the 6-month figure, so Q2 and Q3 are unknown, but Q3 year-to-date is.
    raw = flow_facts(
        "Revenues", {2023: (100, 110, 120, 130)}, ytd_only=True, skip=frozenset({(2023, 2)})
    ) + flow_facts("CostOfRevenue", {2023: (1, 1, 1, 1)})  # another flow supplies the calendar

    revenue = row(revenue_table("quarterly", raw), "revenue")

    assert revenue.values == [100, None, None, 460 - 330]
    assert revenue.provenance == ["reported", None, None, "derived"]


def test_q4_falls_back_to_fy_minus_the_three_discrete_quarters() -> None:
    stripped = [
        r
        for r in flow_facts("Revenues", {2023: (100, 110, 120, 130)})
        if r["period_start"] != date(2022, 7, 1)
        or r["period_end"] in {date(2022, 9, 30), date(2023, 6, 30)}
    ]  # revenue lacks the 6- and 9-month year-to-date facts
    # another mapped flow still supplies them: the calendar is read from every mapped flow
    raw = stripped + flow_facts("CostOfRevenue", {2023: (1, 1, 1, 1)})

    revenue = row(revenue_table("quarterly", raw), "revenue")

    assert revenue.values == [100, 110, 120, 130]
    assert revenue.provenance == ["reported", "reported", "reported", "derived"]


def test_average_items_have_fy_and_reported_quarters_but_no_q4() -> None:
    raw = flow_facts("EarningsPerShareDiluted", {2023: (1, 1, 2, 2)}, unit="USD/shares")
    raw += flow_facts("Revenues", {2023: (1, 1, 1, 1)})  # defines the calendar

    annual = build(raw, IS_ITEMS, IS_MAP, "IS", "annual")
    quarterly = build(raw, IS_ITEMS, IS_MAP, "IS", "quarterly")

    assert row(annual, "eps_diluted").values == [6]
    # Q2 and Q3 have 3-month facts here, Q4 never exists
    assert row(quarterly, "eps_diluted").values == [1, 1, 2, None]
    assert row(quarterly, "eps_diluted").provenance == ["reported", "reported", "reported", None]


def test_average_items_are_not_derived_from_year_to_date_facts() -> None:
    raw = flow_facts(
        "EarningsPerShareDiluted", {2023: (1, 1, 2, 2)}, ytd_only=True, unit="USD/shares"
    )
    raw += flow_facts("Revenues", {2023: (1, 1, 1, 1)})  # defines the calendar

    values = row(build(raw, IS_ITEMS, IS_MAP, "IS", "quarterly"), "eps_diluted").values

    assert values == [1, None, None, None]


def test_a_year_with_only_two_10qs_has_no_quarters_but_keeps_its_annual_value() -> None:
    raw = flow_facts(
        "Revenues", {2022: (1, 2, 3, 4), 2023: (5, 6, 7, 8)}, skip=frozenset({(2023, 3)})
    )

    quarterly = revenue_table("quarterly", raw)
    annual = revenue_table("annual", raw)

    assert keys(quarterly) == [f"FY2022Q{n}" for n in (1, 2, 3, 4)]
    assert any("2023" in w for w in quarterly.warnings)
    assert row(annual, "revenue").values == [10, 26]


def test_a_trailing_open_year_shows_its_reported_quarters_but_no_q4() -> None:
    raw = flow_facts("Revenues", REVENUE)
    raw.append(
        fact("Revenues", date(2023, 7, 1), date(2023, 9, 30), 190, accession="Q1-2024", form="10-Q")
    )

    annual = revenue_table("annual", raw)
    quarterly = revenue_table("quarterly", raw)

    assert keys(annual) == ["FY2022", "FY2023"]
    assert keys(quarterly)[-1] == "FY2024Q1"
    assert row(quarterly, "revenue").values[-1] == 190
    assert row(quarterly, "revenue").provenance[-1] == "reported"


def test_instants_take_the_value_at_the_period_end_and_q4_is_the_year_end() -> None:
    raw = instant_facts("Cash", {2023: (5, 6, 7, 8)})
    raw += flow_facts("Revenues", {2023: (1, 1, 1, 1)})  # defines the calendar

    table = build(raw, BS_ITEMS + IS_ITEMS, IS_BS_MAP, "BS", "quarterly")

    cash = row(table, "cash")
    assert cash.values == [5, 6, 7, 8]
    assert cash.provenance == ["reported"] * 4


# --- derive and residual -------------------------------------------------------------------


def test_derive_fills_a_period_only_when_no_concept_has_a_value() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts(
        "CostOfRevenue", {2022: (40, 40, 40, 40), 2023: (50, 50, 50, 50)}
    )
    # a mapped GrossProfit exists for FY2023 only, and disagrees with the formula
    start, end, _ = fy_dates(2023)
    raw.append(fact("GrossProfit", start, end, 999, accession="K-2023"))

    table = revenue_table("annual", raw)

    gross_profit = row(table, "gross_profit")
    assert gross_profit.values == [460 - 160, 999]
    assert gross_profit.provenance == ["derived", "reported"]


def test_derive_is_null_when_an_operand_is_missing() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2023: (50, 50, 50, 50)})

    gross_profit = row(revenue_table("annual", raw), "gross_profit")

    assert gross_profit.values == [None, 660 - 200]
    assert gross_profit.provenance == [None, "derived"]


def test_derived_values_apply_to_quarters_too() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2023: (50, 60, 70, 80)})

    gross_profit = row(revenue_table("quarterly", raw), "gross_profit")

    assert gross_profit.values[4:] == [100, 100, 100, 100]
    assert set(gross_profit.provenance[4:]) == {"derived"}


def balance_sheet(
    cash: int | None = 10,
    receivables: int | None = 20,
    current: int | None = 100,
    assets: int | None = 500,
    common_size_base: str = "total",
) -> StatementTable:
    raw = flow_facts("Revenues", {2023: (1, 1, 1, 1)})  # defines the calendar
    for concept, value in (
        ("Cash", cash),
        ("Receivables", receivables),
        ("AssetsCurrent", current),
        ("Assets", assets),
    ):
        if value is not None:
            raw += instant_facts(concept, {2023: (value, value, value, value)})
    return build(raw, BS_ITEMS + IS_ITEMS, IS_BS_MAP, "BS", "annual", common_size_base)


def test_a_residual_absorbs_what_the_other_components_do_not_explain() -> None:
    other = row(balance_sheet(), "other_current_assets")

    assert other.values == [100 - 10 - 20]
    assert other.provenance == ["derived"]


def test_a_residual_treats_a_missing_component_as_zero() -> None:
    other = row(balance_sheet(receivables=None), "other_current_assets")

    assert other.values == [100 - 10]


def test_a_residual_is_null_without_its_subtotal() -> None:
    other = row(balance_sheet(current=None), "other_current_assets")

    assert other.values == [None]
    assert other.provenance == [None]


def test_total_liabilities_falls_back_to_total_less_equity() -> None:
    raw = flow_facts("Revenues", {2023: (1, 1, 1, 1)})
    for concept, value in (("Equity", 200), ("LiabilitiesAndEquity", 500)):
        raw += instant_facts(concept, {2023: (value, value, value, value)})

    liabilities = row(
        build(raw, BS_ITEMS + IS_ITEMS, IS_BS_MAP, "BS", "annual"), "total_liabilities"
    )

    assert liabilities.values == [300]
    assert liabilities.provenance == ["derived"]


# --- shape ---------------------------------------------------------------------------------


def test_rows_follow_item_order_with_depth_from_the_parent_chain() -> None:
    table = balance_sheet()

    assert [r.code for r in table.rows] == [i.code for i in BS_ITEMS]
    depth = {r.code: r.depth for r in table.rows}
    assert depth["total_assets"] == 0
    assert depth["total_current_assets"] == 1
    assert depth["cash"] == 2
    assert row(table, "cash").label == "Cash"
    assert row(table, "cash").kind == "instant"
    assert row(table, "cash").unit == "USD"


def test_every_row_array_is_aligned_with_the_periods() -> None:
    table = revenue_table("quarterly")

    for r in table.rows:
        assert (
            len(r.values)
            == len(r.provenance)
            == len(r.yoy)
            == len(r.common_size)
            == len(table.periods)
        )


def test_an_empty_frame_gives_no_periods_and_empty_rows() -> None:
    table = build([], IS_ITEMS, IS_MAP, "IS", "annual")

    assert table.periods == []
    assert [r.values for r in table.rows] == [[]] * len(IS_ITEMS)


def test_balance_sheets_have_no_ttm() -> None:
    with pytest.raises(ValueError):
        build([], BS_ITEMS, BS_MAP, "BS", "ttm")


# --- invariants ----------------------------------------------------------------------------


def test_the_four_quarters_add_up_to_the_fiscal_year_for_every_flow_row() -> None:
    quarters = {2021: (90, 95, 100, 105), 2022: (100, 110, 120, 130), 2023: (150, 160, 170, 180)}
    raw = flow_facts("Revenues", quarters) + flow_facts(
        "CostOfRevenue", {y: tuple(v // 2 for v in q) for y, q in quarters.items()}
    )
    items = IS_ITEMS + [item("cfo", "IS")]
    raw += flow_facts("NetCashFromOps", {y: (9, 8, 7, 6) for y in quarters}, ytd_only=True)
    maps = mappings(
        ("revenue", "Revenues", 0),
        ("cost_of_revenue", "CostOfRevenue", 0),
        ("cfo", "NetCashFromOps", 0),
    )
    annual = build(raw, items, maps, "IS", "annual")
    quarterly = build(raw, items, maps, "IS", "quarterly")

    for code in ("revenue", "cost_of_revenue", "gross_profit", "cfo"):
        fy = dict(zip(keys(annual), row(annual, code).values, strict=True))
        by_year: dict[str, Decimal] = {}
        for key, value in zip(keys(quarterly), row(quarterly, code).values, strict=True):
            assert value is not None
            by_year[key[:6]] = by_year.get(key[:6], Decimal(0)) + value
        for year, total in by_year.items():
            assert total == fy[year], (code, year)


# --- TTM -----------------------------------------------------------------------------------


def test_ttm_sums_the_last_four_discrete_quarters() -> None:
    table = revenue_table("ttm")

    revenue = row(table, "revenue")
    assert keys(table) == [
        "TTM-FY2022Q4",
        "TTM-FY2023Q1",
        "TTM-FY2023Q2",
        "TTM-FY2023Q3",
        "TTM-FY2023Q4",
    ]
    assert revenue.values == [460, 510, 560, 610, 660]
    assert set(revenue.provenance) == {"derived"}
    assert table.periods[1].label == "TTM Q1 FY23"


def test_ttm_is_null_for_average_items() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts(
        "EarningsPerShareDiluted", REVENUE, unit="USD/shares"
    )

    eps = row(revenue_table("ttm", raw), "eps_diluted")

    assert eps.values == [None] * 5
    assert eps.provenance == [None] * 5


def test_ttm_is_null_while_a_quarter_is_missing() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2023: (50, 60, 70, 80)})

    gross_profit = row(revenue_table("ttm", raw), "gross_profit")

    assert gross_profit.values == [None, None, None, None, 400]  # only TTM Q4 FY23 has all four


# --- YoY -----------------------------------------------------------------------------------

REVENUE_3Y = {2021: (80, 90, 100, 110), 2022: (100, 110, 120, 130), 2023: (150, 160, 170, 180)}


def test_annual_yoy_is_current_over_prior_minus_one_to_six_places() -> None:
    yoy = row(revenue_table("annual"), "revenue").yoy

    assert yoy == [None, Decimal("0.434783")]  # 660 / 460 - 1


def test_quarterly_yoy_compares_with_the_same_quarter_a_year_earlier() -> None:
    raw = flow_facts("Revenues", REVENUE_3Y)

    yoy = row(revenue_table("quarterly", raw), "revenue").yoy

    assert yoy[:4] == [None] * 4  # FY2021 has no prior year
    assert yoy[4:8] == [
        Decimal("0.250000"),
        Decimal("0.222222"),
        Decimal("0.200000"),
        Decimal("0.181818"),
    ]
    assert yoy[8:] == [
        Decimal("0.500000"),
        Decimal("0.454545"),
        Decimal("0.416667"),
        Decimal("0.384615"),
    ]


def test_ttm_yoy_compares_with_the_ttm_four_quarters_earlier() -> None:
    raw = flow_facts("Revenues", REVENUE_3Y)

    table = revenue_table("ttm", raw)

    yoy = dict(zip(keys(table), row(table, "revenue").yoy, strict=True))
    assert yoy["TTM-FY2022Q4"] is not None
    assert yoy["TTM-FY2023Q1"] == Decimal("0.275000")  # 510 / 400 - 1
    assert yoy["TTM-FY2021Q4"] is None


@pytest.mark.parametrize("prior", [0, -50])
def test_yoy_is_null_unless_the_prior_value_is_positive(prior: int) -> None:
    raw = flow_facts("Revenues", {2022: (prior, 0, 0, 0), 2023: (5, 5, 5, 5)})

    assert row(revenue_table("annual", raw), "revenue").yoy == [None, None]


def test_yoy_is_null_when_the_current_value_is_missing() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts("CostOfRevenue", {2022: (1, 1, 1, 1)})

    assert row(revenue_table("annual", raw), "cost_of_revenue").yoy == [None, None]


# --- common-size ---------------------------------------------------------------------------


def test_income_statement_common_size_is_a_fraction_of_revenue() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts(
        "CostOfRevenue", {2022: (40, 40, 40, 40), 2023: (50, 50, 50, 50)}
    )

    table = revenue_table("annual", raw)

    assert row(table, "revenue").common_size == [Decimal("1.000000"), Decimal("1.000000")]
    assert row(table, "cost_of_revenue").common_size == [Decimal("0.347826"), Decimal("0.303030")]


def test_ttm_common_size_uses_ttm_revenue() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts(
        "CostOfRevenue", {2022: (40, 40, 40, 40), 2023: (50, 50, 50, 50)}
    )

    cost = row(revenue_table("ttm", raw), "cost_of_revenue")

    assert cost.common_size[0] == Decimal("0.347826")  # 160 / 460
    assert cost.common_size[1] == Decimal("0.333333")  # 170 / 510


def test_cash_flow_common_size_is_a_fraction_of_income_statement_revenue() -> None:
    raw = flow_facts("Revenues", REVENUE) + flow_facts(
        "NetCashFromOps", {2022: (10, 10, 10, 10), 2023: (15, 15, 15, 15)}
    )

    table = build(
        raw, IS_ITEMS + CF_ITEMS, pd.concat([IS_MAP, CF_MAP], ignore_index=True), "CF", "annual"
    )

    assert row(table, "cfo").common_size == [Decimal("0.086957"), Decimal("0.090909")]


def test_balance_sheet_common_size_is_a_fraction_of_total_assets() -> None:
    table = balance_sheet(cash=10, assets=500)

    assert row(table, "cash").common_size == [Decimal("0.020000")]
    assert row(table, "total_assets").common_size == [Decimal("1.000000")]


def test_common_size_is_null_without_a_denominator() -> None:
    assert row(balance_sheet(assets=None), "cash").common_size == [None]
    zero_revenue = flow_facts("Revenues", {2023: (0, 0, 0, 0)}) + flow_facts(
        "CostOfRevenue", {2023: (1, 1, 1, 1)}
    )
    assert row(revenue_table("annual", zero_revenue), "cost_of_revenue").common_size == [None]


def test_common_size_names_its_base_on_every_row() -> None:
    income = revenue_table("annual")
    balance = balance_sheet()
    cash_flow = build(
        flow_facts("Revenues", REVENUE) + flow_facts("NetCashFromOps", {2023: (1, 1, 1, 1)}),
        IS_ITEMS + CF_ITEMS,
        pd.concat([IS_MAP, CF_MAP], ignore_index=True),
        "CF",
        "annual",
    )

    assert {r.common_size_base for r in income.rows} == {"Revenue"}
    assert {r.common_size_base for r in balance.rows} == {"Total assets"}
    assert {r.common_size_base for r in cash_flow.rows} == {"Revenue"}


def test_parent_common_size_divides_a_row_by_its_parent() -> None:
    table = balance_sheet(common_size_base="parent")

    assert row(table, "cash").common_size == [Decimal("0.100000")]  # 10 / 100 current assets
    assert row(table, "receivables").common_size == [Decimal("0.200000")]
    assert row(table, "total_current_assets").common_size == [Decimal("0.200000")]  # 100 / 500
    assert row(table, "cash").common_size_base == "Total current assets"
    assert row(table, "total_current_assets").common_size_base == "Total assets"


def test_parent_common_size_falls_back_to_the_total_base_for_a_root_row() -> None:
    balance = balance_sheet(common_size_base="parent")
    raw = flow_facts("Revenues", REVENUE) + flow_facts(
        "CostOfRevenue", {2022: (40, 40, 40, 40), 2023: (50, 50, 50, 50)}
    )
    income = build(raw, IS_ITEMS, IS_MAP, "IS", "annual", "parent")

    assert row(balance, "total_assets").common_size == [Decimal("1.000000")]
    assert row(balance, "total_assets").common_size_base == "Total assets"
    assert row(income, "revenue").common_size_base == "Revenue"
    # cost_of_revenue is a child of gross_profit (revenue - cost): 160 / 300 and 200 / 460
    assert row(income, "cost_of_revenue").common_size_base == "Gross profit"
    assert row(income, "cost_of_revenue").common_size == [Decimal("0.533333"), Decimal("0.434783")]


def test_parent_common_size_is_null_when_the_parent_has_no_value() -> None:
    table = balance_sheet(current=None, common_size_base="parent")

    assert row(table, "cash").common_size == [None]


def test_parent_common_size_of_a_cash_flow_row_is_its_section_total() -> None:
    raw = (
        flow_facts("Revenues", REVENUE)
        + flow_facts("NetCashFromOps", {2023: (10, 10, 10, 10)})
        + flow_facts("PaymentsToAcquirePPE", {2023: (4, 4, 4, 4)})
    )

    table = build(
        raw,
        IS_ITEMS + CF_ITEMS,
        pd.concat([IS_MAP, CF_MAP], ignore_index=True),
        "CF",
        "annual",
        "parent",
    )

    assert row(table, "capex").common_size_base == "Cfo"  # the test item's label
    assert row(table, "capex").common_size == [None, Decimal("-0.400000")]  # an outflow
    assert row(table, "cfo").common_size_base == "Revenue"  # cfo is a root: the total base


# --- balance check -------------------------------------------------------------------------


def checked(assets: int, liabilities: int | None, equity: int | None) -> StatementTable:
    raw = flow_facts("Revenues", {2023: (1, 1, 1, 1)})
    for concept, value in (("Assets", assets), ("Liabilities", liabilities), ("Equity", equity)):
        if value is not None:
            raw += instant_facts(concept, {2023: (value, value, value, value)})
    return build(raw, BS_ITEMS + IS_ITEMS, IS_BS_MAP, "BS", "annual")


def test_a_balanced_period_passes_the_check() -> None:
    (check,) = checked(500_000_000, 300_000_000, 200_000_000).balance_check or []

    assert (check.period_key, check.difference, check.ok) == ("FY2023", 0, True)


def test_a_small_difference_is_within_the_tolerance() -> None:
    (check,) = checked(500_000_000, 300_000_000, 199_500_000).balance_check or []

    assert check.difference == 500_000 and check.ok


def test_an_unbalanced_period_fails_the_check() -> None:
    (check,) = checked(500_000_000, 300_000_000, 198_000_000).balance_check or []

    assert check.difference == 2_000_000 and not check.ok


def test_the_tolerance_scales_with_total_assets() -> None:
    assert (checked(10**12, 6 * 10**11, 4 * 10**11 - 5_000_000).balance_check or [])[0].ok
    assert not (checked(10**12, 6 * 10**11, 4 * 10**11 - 20_000_000).balance_check or [])[0].ok


def test_a_period_missing_a_total_fails_with_no_difference() -> None:
    (check,) = checked(500_000_000, None, 200_000_000).balance_check or []

    assert check.difference is None and not check.ok


def test_every_quarter_is_checked() -> None:
    raw = flow_facts("Revenues", {2023: (1, 1, 1, 1)})
    for concept, value in (("Assets", 500), ("Liabilities", 300), ("Equity", 200)):
        raw += instant_facts(concept, {2023: (value, value, value, value)})

    table = build(raw, BS_ITEMS + IS_ITEMS, IS_BS_MAP, "BS", "quarterly")

    assert [c.period_key for c in table.balance_check or []] == keys(table)
    assert all(c.ok for c in table.balance_check or [])


def test_only_the_balance_sheet_has_a_balance_check() -> None:
    assert revenue_table("annual").balance_check is None
