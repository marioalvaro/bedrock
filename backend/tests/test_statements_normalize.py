"""Normalization: reported + adjustments, with propagation (ERD data.md, "Adjustments and the
normalized view"). Pure: FictCo has a June fiscal year; its quarters end 30 Sep, 31 Dec, 31 Mar."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import IdentityDef, SolveRule
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cells import EMPTY, Cell
from bedrock.statements.normalize import AppliedAdjustment, apply_adjustments
from bedrock.statements.periods import Calendar, FiscalYear
from bedrock.statements.rules import Rules
from tests.engine_data import Row as FactRow
from tests.engine_data import fact, facts, flow_facts, fy_dates, instant_facts, item, mappings

D = Decimal
B = 1_000_000_000
EXACT = SolveRule("exact", None)


@dataclass(frozen=True)
class Adj:
    """Any object with these attributes is an adjustment (the ORM row has them too)."""

    id: int
    canonical_code: str
    fiscal_year: int
    fiscal_period: str
    amount: Decimal


def adj(id_: int, code: str, fiscal_year: int, fiscal_period: str, amount: int | str) -> Adj:
    return Adj(id_, code, fiscal_year, fiscal_period, D(str(amount)))


ITEMS = [
    # income statement
    item("revenue", rolls_into=[("gross_profit", 1)]),
    item("cost_of_revenue", rolls_into=[("gross_profit", -1)]),
    item("gross_profit", derive="revenue - cost_of_revenue", rolls_into=[("operating_income", 1)]),
    item("total_operating_costs", derive="gross_profit - operating_income"),
    item("sga", parent="total_operating_costs", rolls_into=[("operating_income", -1)]),
    item(
        "other_operating_expenses",
        parent="total_operating_costs",
        derive="gross_profit - sga - operating_income",
        residual=True,
        rolls_into=[("operating_income", -1)],
    ),
    item("operating_income", rolls_into=[("pretax_income", 1)]),
    item("pretax_income", rolls_into=[("net_income", 1)]),
    item("net_income", rolls_into=[("net_income_common", 1)]),
    item("net_income_common"),
    item("eps_diluted", kind="average", unit="USD/shares"),
    item("shares_diluted", kind="average", unit="shares"),
    # balance sheet (parents are sums of their children)
    item("cash", "BS", kind="instant", parent="total_current_assets"),
    item("total_current_assets", "BS", kind="instant", parent="total_assets"),
    item("total_assets", "BS", kind="instant"),
    item("short_term_debt", "BS", kind="instant", parent="total_liabilities"),
    item("long_term_debt", "BS", kind="instant", parent="total_liabilities"),
    item(
        "total_liabilities",
        "BS",
        kind="instant",
        rolls_into=[("total_liabilities_and_equity", 1)],
    ),
    item("total_equity", "BS", kind="instant", rolls_into=[("total_liabilities_and_equity", 1)]),
    item("total_liabilities_and_equity", "BS", kind="instant"),
    item("total_debt", "BS", kind="instant", derive="short_term_debt + long_term_debt"),
    # cash flow
    item("cfo", "CF", rolls_into=[("net_change_in_cash", 1)]),
    item("capex", "CF", sign=-1, parent="cfi"),
    item("cfi", "CF", rolls_into=[("net_change_in_cash", 1)]),
    item("free_cash_flow", "CF", derive="cfo + capex"),
    item("net_change_in_cash", "CF"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("sga", "SellingGeneralAndAdministrativeExpense", 0),
    ("operating_income", "OperatingIncomeLoss", 0),
    ("pretax_income", "IncomeLossBeforeTax", 0),
    ("net_income", "NetIncomeLoss", 0),
    ("net_income_common", "NetIncomeLossCommon", 0),
    ("eps_diluted", "EarningsPerShareDiluted", 0),
    ("shares_diluted", "WeightedAverageShares", 0),
    ("cash", "Cash", 0),
    ("total_current_assets", "AssetsCurrent", 0),
    ("total_assets", "Assets", 0),
    ("short_term_debt", "DebtCurrent", 0),
    ("long_term_debt", "LongTermDebt", 0),
    ("total_liabilities", "Liabilities", 0),
    ("total_equity", "Equity", 0),
    ("total_liabilities_and_equity", "LiabilitiesAndEquity", 0),
    ("cfo", "NetCashFromOps", 0),
    ("capex", "PaymentsToAcquirePPE", 0),
    ("cfi", "NetCashInvesting", 0),
    ("net_change_in_cash", "NetChangeInCash", 0),
)


def raw() -> list[FactRow]:
    def flows(concept: str, fy22: Sequence[int] | None, fy23: Sequence[int]) -> list[FactRow]:
        quarters = {2023: tuple(fy23)}
        if fy22 is not None:
            quarters[2022] = tuple(fy22)
        return flow_facts(concept, quarters)

    rows: list[FactRow] = []
    rows += flows("Revenues", (100, 110, 120, 130), (150, 160, 170, 180))
    rows += flows("CostOfRevenue", (40, 40, 40, 40), (50, 50, 50, 50))
    rows += flows("SellingGeneralAndAdministrativeExpense", None, (10, 10, 10, 10))
    rows += flows("OperatingIncomeLoss", (30, 40, 50, 60), (60, 70, 80, 90))
    rows += flows("IncomeLossBeforeTax", (28, 38, 48, 58), (55, 65, 75, 85))
    rows += flows("NetIncomeLoss", (20, 30, 40, 50), (40, 50, 60, 70))
    rows += flows("NetIncomeLossCommon", (20, 30, 40, 50), (40, 50, 60, 70))
    rows += flows("NetCashFromOps", None, (20, 20, 20, 20))
    rows += flows("PaymentsToAcquirePPE", None, (5, 5, 5, 5))
    rows += flows("NetCashInvesting", None, (-8, -8, -8, -8))
    rows += flows("NetChangeInCash", None, (10, 10, 10, 10))
    rows += flow_facts("EarningsPerShareDiluted", {2022: (1, 1, 1, 1)}, unit="USD/shares")
    rows += flow_facts("EarningsPerShareDiluted", {2023: (2, 2, 2, 2)}, unit="USD/shares")
    # weighted shares: 10 in every quarter and in the year (the helper would sum them to 40)
    shares = flow_facts("WeightedAverageShares", {2023: (10, 10, 10, 10)}, unit="shares")
    start, end, _ = fy_dates(2023)
    rows += [r for r in shares if not str(r["accession_no"]).startswith("K-")]
    rows.append(fact("WeightedAverageShares", start, end, 10, accession="K-2023", unit="shares"))
    for concept, fy22, fy23 in (
        ("Cash", (20, 21, 22, 23), (24, 25, 26, 27)),
        ("AssetsCurrent", (40, 41, 42, 43), (50, 51, 52, 53)),
        ("Assets", (80, 81, 82, 83), (100, 101, 102, 103)),
        ("DebtCurrent", (5, 5, 5, 5), (5, 5, 5, 5)),
        ("LongTermDebt", (30, 30, 30, 30), (30, 30, 30, 30)),
        ("Liabilities", (48, 49, 50, 51), (60, 61, 62, 63)),
        ("Equity", (32, 32, 32, 32), (40, 40, 40, 40)),
        ("LiabilitiesAndEquity", (80, 81, 82, 83), (100, 101, 102, 103)),
    ):
        rows += instant_facts(concept, {2022: fy22, 2023: fy23})
    return rows


FRAME = map_facts(select_vintage(facts(raw())), MAPS, ITEMS)


def table(statement: str, freq: str, adjustments: Sequence[Adj] = ()) -> StatementTable:
    return build_statement(FRAME, ITEMS, statement, freq, adjustments=adjustments)  # type: ignore[arg-type]


def series(t: StatementTable, code: str) -> dict[str, Decimal | None]:
    row = next(r for r in t.rows if r.code == code)
    return {p.key: v for p, v in zip(t.periods, row.values, strict=True)}


def provenance(t: StatementTable, code: str) -> dict[str, str | None]:
    row = next(r for r in t.rows if r.code == code)
    return {p.key: v for p, v in zip(t.periods, row.provenance, strict=True)}


def q(t: StatementTable, code: str, year: int = 2023) -> list[Decimal | None]:
    values = series(t, code)
    return [values[f"FY{year}Q{n}"] for n in (1, 2, 3, 4)]


# --- the reported basis ----------------------------------------------------------------------


def test_no_adjustments_leaves_the_table_as_reported() -> None:
    plain = table("IS", "quarterly")
    again = table("IS", "quarterly", [])

    assert plain == again
    assert "normalized" not in {p for r in plain.rows for p in r.provenance}


def test_apply_adjustments_does_not_touch_the_cells_it_is_given() -> None:
    calendar = Calendar((FiscalYear(2023, date(2022, 7, 1), date(2023, 6, 30), ()),), ())
    cells = {("sga", "FY2023"): Cell(D(10), "reported")}

    out, _ = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", -5)], calendar)

    assert cells == {("sga", "FY2023"): Cell(D(10), "reported")}
    assert out[("sga", "FY2023")].value == 5


# --- flows: period mapping --------------------------------------------------------------------


def test_a_quarter_adjustment_changes_the_quarter_and_the_year_and_keeps_q1_to_q4_equal_to_fy() -> (
    None
):
    adjustments = [adj(1, "sga", 2023, "Q2", -5)]
    quarterly = table("IS", "quarterly", adjustments)
    annual = table("IS", "annual", adjustments)

    assert q(quarterly, "sga") == [10, 5, 10, 10]
    assert series(annual, "sga")["FY2023"] == 35
    for code in (
        "sga",
        "operating_income",
        "pretax_income",
        "net_income",
        "net_income_common",
        "gross_profit",
        "total_operating_costs",
        "other_operating_expenses",
    ):
        quarters = q(quarterly, code)
        assert None not in quarters, code
        assert sum(v for v in quarters if v is not None) == series(annual, code)["FY2023"], code


def test_a_quarter_adjustment_flows_down_the_income_statement_waterfall() -> None:
    quarterly = table("IS", "quarterly", [adj(1, "sga", 2023, "Q2", -5)])

    # an expense removed raises every profit line below it, by the same amount
    assert q(quarterly, "operating_income") == [60, 75, 80, 90]
    assert q(quarterly, "pretax_income") == [55, 70, 75, 85]
    assert q(quarterly, "net_income") == [40, 55, 60, 70]
    assert q(quarterly, "net_income_common") == [40, 55, 60, 70]
    assert q(quarterly, "revenue") == [150, 160, 170, 180]  # above the line: untouched


def test_a_fy_flow_adjustment_lands_in_q4() -> None:
    adjustments = [adj(1, "sga", 2023, "FY", -8)]
    quarterly = table("IS", "quarterly", adjustments)
    annual = table("IS", "annual", adjustments)

    assert q(quarterly, "sga") == [10, 10, 10, 2]
    assert series(annual, "sga")["FY2023"] == 32
    assert q(quarterly, "operating_income") == [60, 70, 80, 98]
    assert series(annual, "operating_income")["FY2023"] == 308


def test_a_q4_flow_adjustment_changes_q4_and_the_year() -> None:
    adjustments = [adj(1, "sga", 2023, "Q4", 3)]

    assert q(table("IS", "quarterly", adjustments), "sga") == [10, 10, 10, 13]
    assert series(table("IS", "annual", adjustments), "sga")["FY2023"] == 43


def test_ttm_is_recomputed_from_the_adjusted_quarters() -> None:
    ttm = table("IS", "ttm", [adj(1, "sga", 2023, "Q2", -5)])

    values = series(ttm, "operating_income")
    # TTM-FY2023Q1 ends before Q2; the three later windows contain the adjusted quarter
    assert values["TTM-FY2023Q1"] == 210
    assert values["TTM-FY2023Q2"] == 245
    assert values["TTM-FY2023Q3"] == 275
    assert values["TTM-FY2023Q4"] == 305
    marks = provenance(ttm, "operating_income")
    assert marks["TTM-FY2023Q1"] == "derived"
    assert marks["TTM-FY2023Q2"] == marks["TTM-FY2023Q4"] == "normalized"


# --- instants ---------------------------------------------------------------------------------


def test_an_instant_adjustment_on_a_quarter_applies_at_that_quarter_end_only() -> None:
    adjustments = [adj(1, "cash", 2023, "Q2", 10)]
    quarterly = table("BS", "quarterly", adjustments)
    annual = table("BS", "annual", adjustments)

    assert q(quarterly, "cash") == [24, 35, 26, 27]
    assert series(annual, "cash")["FY2023"] == 27


def test_an_instant_adjustment_on_fy_or_q4_applies_to_both_the_year_end_and_q4() -> None:
    for period in ("FY", "Q4"):
        adjustments = [adj(1, "cash", 2023, period, 10)]
        quarterly = table("BS", "quarterly", adjustments)
        annual = table("BS", "annual", adjustments)

        assert q(quarterly, "cash") == [24, 25, 26, 37], period
        assert series(annual, "cash")["FY2023"] == 37, period


def test_a_balance_sheet_adjustment_rolls_into_the_parent_subtotals() -> None:
    quarterly = table("BS", "quarterly", [adj(1, "cash", 2023, "Q2", 10)])

    assert q(quarterly, "total_current_assets") == [50, 61, 52, 53]
    assert q(quarterly, "total_assets") == [100, 111, 102, 103]
    assert q(quarterly, "total_liabilities") == [60, 61, 62, 63]


def test_a_balanced_pair_keeps_the_balance_sheet_balanced() -> None:
    pair = [adj(1, "cash", 2023, "Q2", 10), adj(2, "long_term_debt", 2023, "Q2", 10)]
    quarterly = table("BS", "quarterly", pair)

    assert quarterly.balance_check is not None
    differences = {c.period_key: c.difference for c in quarterly.balance_check}
    assert all(v == 0 for k, v in differences.items() if k.startswith("FY2023")), differences
    assert q(quarterly, "total_liabilities") == [60, 71, 62, 63]
    assert q(quarterly, "total_liabilities_and_equity") == [100, 111, 102, 103]


def test_an_unbalanced_adjustment_shows_up_in_the_balance_check() -> None:
    quarterly = table("BS", "quarterly", [adj(1, "cash", 2023, "Q2", 10)])

    assert quarterly.balance_check is not None
    differences = {c.period_key: c.difference for c in quarterly.balance_check}
    assert differences["FY2023Q2"] == 10
    assert differences["FY2023Q1"] == 0


# --- residuals and computed-only lines --------------------------------------------------------


def footing(t: StatementTable, n: int = 1) -> tuple[Decimal, Decimal, Decimal]:
    """gross profit - sga - residual - operating income of quarter n+1 (0 when it foots), and the
    residual and operating income themselves."""
    gp, sga, other, oi = (
        q(t, c)[n] for c in ("gross_profit", "sga", "other_operating_expenses", "operating_income")
    )
    assert gp is not None and sga is not None and other is not None and oi is not None
    return gp - sga - other - oi, other, oi


def test_components_and_residual_still_foot_to_the_subtotal_after_a_component_changes() -> None:
    quarterly = table("IS", "quarterly", [adj(1, "sga", 2023, "Q2", -5)])

    gap, other, _ = footing(quarterly)
    assert other == 30  # not recomputed: the delta reached operating income through the waterfall
    assert gap == 0


def test_adjusting_the_residual_itself_moves_the_subtotal_and_keeps_the_footing() -> None:
    quarterly = table("IS", "quarterly", [adj(1, "other_operating_expenses", 2023, "Q2", 3)])

    gap, other, oi = footing(quarterly)
    assert other == 33 and oi == 67
    assert gap == 0


def test_computed_only_lines_are_recomputed_from_the_adjusted_cells() -> None:
    quarterly = table("IS", "quarterly", [adj(1, "sga", 2023, "Q2", -5)])

    assert q(quarterly, "total_operating_costs") == [40, 35, 40, 40]
    assert provenance(quarterly, "total_operating_costs")["FY2023Q2"] == "normalized"
    assert provenance(quarterly, "total_operating_costs")["FY2023Q1"] == "derived"


def test_total_debt_follows_a_debt_adjustment() -> None:
    annual = table("BS", "annual", [adj(1, "short_term_debt", 2023, "FY", 3)])

    assert series(annual, "short_term_debt")["FY2023"] == 8
    assert series(annual, "total_debt")["FY2023"] == 38
    assert provenance(annual, "total_debt")["FY2023"] == "normalized"


def test_free_cash_flow_follows_a_capex_adjustment() -> None:
    adjustments = [adj(1, "capex", 2023, "Q3", -2)]  # displayed negative: more spending
    quarterly = table("CF", "quarterly", adjustments)
    annual = table("CF", "annual", adjustments)

    assert q(quarterly, "capex") == [-5, -5, -7, -5]
    assert q(quarterly, "free_cash_flow") == [15, 15, 13, 15]
    assert series(annual, "capex")["FY2023"] == -22
    assert series(annual, "free_cash_flow")["FY2023"] == 58
    assert q(quarterly, "cfi") == [-8, -8, -10, -8]  # capex's parent, via the section total
    assert q(quarterly, "net_change_in_cash") == [10, 10, 8, 10]
    assert q(quarterly, "cfo") == [20, 20, 20, 20]


# --- EPS --------------------------------------------------------------------------------------


def test_eps_moves_by_the_change_in_net_income_over_the_shares_of_the_period() -> None:
    adjustments = [adj(1, "sga", 2023, "Q2", -5)]  # +5 to net income common
    quarterly = table("IS", "quarterly", adjustments)
    annual = table("IS", "annual", adjustments)

    assert q(quarterly, "eps_diluted") == [2, D("2.5"), 2, None]
    assert series(annual, "eps_diluted")["FY2023"] == D("8.5")  # 8 + 5 / 10
    assert provenance(quarterly, "eps_diluted")["FY2023Q2"] == "normalized"
    assert provenance(quarterly, "eps_diluted")["FY2023Q1"] == "reported"


def test_eps_is_null_when_net_income_changes_and_the_shares_are_missing() -> None:
    quarterly = table("IS", "quarterly", [adj(1, "net_income_common", 2022, "Q1", 5)])

    assert series(quarterly, "eps_diluted")["FY2022Q1"] is None
    assert series(quarterly, "net_income_common")["FY2022Q1"] == 25


def test_eps_is_untouched_when_net_income_does_not_change() -> None:
    income = table("IS", "quarterly", [adj(1, "cash", 2023, "Q2", 10)])  # a balance sheet line

    assert q(income, "eps_diluted") == [2, 2, 2, None]
    assert provenance(income, "eps_diluted")["FY2023Q2"] == "reported"


def test_the_share_counts_are_never_adjusted() -> None:
    quarterly = table("IS", "quarterly", [adj(1, "sga", 2023, "Q2", -5)])

    assert q(quarterly, "shares_diluted") == [10, 10, 10, 10]  # Q4 is rebuilt (R2), not adjusted
    assert provenance(quarterly, "shares_diluted")["FY2023Q4"] == "approximated"


# --- the applied map --------------------------------------------------------------------------


def calendar() -> Calendar:
    q_ends = (date(2022, 9, 30), date(2022, 12, 31), date(2023, 3, 31))
    return Calendar((FiscalYear(2023, date(2022, 7, 1), date(2023, 6, 30), q_ends),), ())


def hand_cells(*codes: str) -> dict[tuple[str, str], Cell]:
    return {
        (code, key): Cell(D(100), "reported")
        for code in codes
        for key in ("FY2023", "FY2023Q1", "FY2023Q2", "FY2023Q3", "FY2023Q4")
    }


def test_applied_lists_each_changed_cell_with_the_adjusted_code_as_via_when_propagated() -> None:
    cells = hand_cells("sga", "operating_income", "pretax_income", "revenue")

    _, applied = apply_adjustments(cells, ITEMS, [adj(7, "sga", 2023, "Q2", -5)], calendar())

    assert applied[("sga", "FY2023Q2")] == [AppliedAdjustment(7, "sga", D(-5), None)]
    assert applied[("sga", "FY2023")] == [AppliedAdjustment(7, "sga", D(-5), None)]
    assert applied[("operating_income", "FY2023Q2")] == [AppliedAdjustment(7, "sga", D(-5), "sga")]
    assert applied[("pretax_income", "FY2023")] == [AppliedAdjustment(7, "sga", D(-5), "sga")]
    assert ("sga", "FY2023Q1") not in applied
    assert not any(code == "revenue" for code, _ in applied)


def test_applied_collects_several_adjustments_of_one_cell() -> None:
    cells = hand_cells("sga", "operating_income")

    out, applied = apply_adjustments(
        cells,
        ITEMS,
        [adj(1, "sga", 2023, "Q2", -5), adj(2, "operating_income", 2023, "Q2", 1)],
        calendar(),
    )

    assert out[("operating_income", "FY2023Q2")].value == 106  # 100 + 5 + 1
    assert [a.adjustment_id for a in applied[("operating_income", "FY2023Q2")]] == [1, 2]


def test_applied_of_a_recomputed_total_is_ordered_by_adjustment_id_not_operand_order() -> None:
    cells = hand_cells("short_term_debt", "long_term_debt", "total_debt")

    _, applied = apply_adjustments(
        cells,
        ITEMS,
        [adj(1, "long_term_debt", 2023, "FY", 5), adj(2, "short_term_debt", 2023, "FY", 3)],
        calendar(),
    )

    # the formula lists short_term_debt first, so operand order would give [2, 1]
    for key in ("FY2023", "FY2023Q4"):
        assert [a.adjustment_id for a in applied[("total_debt", key)]] == [1, 2]


def test_applied_of_free_cash_flow_is_ordered_by_adjustment_id_not_operand_order() -> None:
    cells = hand_cells("cfo", "capex", "free_cash_flow")

    _, applied = apply_adjustments(
        cells,
        ITEMS,
        [adj(1, "capex", 2023, "Q2", -2), adj(2, "cfo", 2023, "Q2", 4)],
        calendar(),
    )

    assert [a.adjustment_id for a in applied[("free_cash_flow", "FY2023Q2")]] == [1, 2]


def test_applied_is_ordered_by_adjustment_id_when_adjustments_are_passed_out_of_order() -> None:
    cells = hand_cells("sga", "operating_income")

    _, applied = apply_adjustments(
        cells,
        ITEMS,
        [adj(2, "operating_income", 2023, "Q2", 1), adj(1, "sga", 2023, "Q2", -5)],
        calendar(),
    )

    assert [a.adjustment_id for a in applied[("operating_income", "FY2023Q2")]] == [1, 2]


def test_applied_keeps_the_input_order_of_entries_that_share_an_adjustment_id() -> None:
    cells = hand_cells("sga", "operating_income")

    _, applied = apply_adjustments(
        cells,
        ITEMS,
        [
            adj(2, "sga", 2023, "Q2", -1),
            adj(1, "sga", 2023, "Q2", -2),
            adj(1, "sga", 2023, "Q2", -3),
        ],
        calendar(),
    )

    entries = applied[("sga", "FY2023Q2")]
    assert [(a.adjustment_id, a.amount) for a in entries] == [(1, D(-2)), (1, D(-3)), (2, D(-1))]


def test_changed_cells_are_normalized_and_keep_their_source() -> None:
    cells = hand_cells("sga", "operating_income")

    out, _ = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", -5)], calendar())

    assert out[("sga", "FY2023")].provenance == "normalized"
    assert out[("sga", "FY2023Q4")].provenance == "normalized"
    assert out[("sga", "FY2023Q1")] == cells[("sga", "FY2023Q1")]


EPS_ITEMS = [*ITEMS, item("eps_basic", kind="average", unit="USD/shares")]


def test_an_eps_emptied_for_missing_shares_still_lists_the_adjustments_behind_it() -> None:
    cells = hand_cells("net_income_common", "eps_basic", "eps_diluted")  # no share counts

    out, applied = apply_adjustments(
        cells, EPS_ITEMS, [adj(3, "net_income_common", 2023, "Q2", 5)], calendar()
    )

    for eps in ("eps_diluted", "eps_basic"):
        assert out[(eps, "FY2023Q2")] == EMPTY
        assert applied[(eps, "FY2023Q2")] == [
            AppliedAdjustment(3, "net_income_common", D(5), "net_income_common")
        ]
        assert applied[(eps, "FY2023")] == applied[(eps, "FY2023Q2")]
    assert ("eps_diluted", "FY2023Q1") not in applied


def test_an_emptied_eps_lists_every_adjustment_behind_it_ordered_by_id() -> None:
    cells = hand_cells("sga", "operating_income", "pretax_income", "net_income")
    cells.update(hand_cells("net_income_common", "eps_diluted"))

    out, applied = apply_adjustments(
        cells,
        ITEMS,
        [adj(4, "net_income_common", 2023, "Q2", 1), adj(2, "sga", 2023, "Q2", -5)],
        calendar(),
    )

    assert out[("eps_diluted", "FY2023Q2")] == EMPTY
    assert applied[("eps_diluted", "FY2023Q2")] == [
        AppliedAdjustment(2, "sga", D(-5), "sga"),  # via names the adjusted line
        AppliedAdjustment(4, "net_income_common", D(1), "net_income_common"),
    ]


def test_an_eps_with_shares_keeps_its_normalized_value_and_lists_its_adjustments() -> None:
    cells = hand_cells("net_income_common", "eps_diluted", "shares_diluted")

    out, applied = apply_adjustments(
        cells, ITEMS, [adj(3, "net_income_common", 2023, "Q2", 50)], calendar()
    )

    assert out[("eps_diluted", "FY2023Q2")].value == 100.5  # 100 + 50 / 100 shares
    assert applied[("eps_diluted", "FY2023Q2")] == [
        AppliedAdjustment(3, "net_income_common", D(50), "net_income_common")
    ]


# --- edge cases -------------------------------------------------------------------------------


def test_an_adjustment_on_an_empty_line_sets_its_value_and_empty_targets_stay_empty() -> None:
    cells = {("sga", "FY2023"): EMPTY}

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", 4)], calendar())

    assert out[("sga", "FY2023")].value == 4
    assert out[("sga", "FY2023")].provenance == "normalized"
    assert out.get(("operating_income", "FY2023"), EMPTY).value is None
    assert ("operating_income", "FY2023") not in applied


def empty_at(
    cells: dict[tuple[str, str], Cell], *keys: tuple[str, str]
) -> dict[tuple[str, str], Cell]:
    return {k: (EMPTY if k in keys else v) for k, v in cells.items()}


def test_an_fy_flow_adjustment_does_not_invent_a_value_in_an_empty_q4() -> None:
    cells = empty_at(hand_cells("sga"), ("sga", "FY2023Q4"))

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", -5)], calendar())

    assert out[("sga", "FY2023")].value == 95
    assert out[("sga", "FY2023Q4")].value is None
    assert ("sga", "FY2023Q4") not in applied


def test_a_quarter_flow_adjustment_does_not_invent_a_value_in_an_empty_year() -> None:
    cells = empty_at(hand_cells("sga"), ("sga", "FY2023"))

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "Q2", -5)], calendar())

    assert out[("sga", "FY2023Q2")].value == 95
    assert out[("sga", "FY2023")].value is None
    assert ("sga", "FY2023") not in applied


def test_a_q4_flow_adjustment_does_not_invent_a_value_in_an_empty_year() -> None:
    cells = empty_at(hand_cells("sga"), ("sga", "FY2023"))

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "Q4", -5)], calendar())

    assert out[("sga", "FY2023Q4")].value == 95
    assert out[("sga", "FY2023")].value is None
    assert ("sga", "FY2023") not in applied


PERIOD_KEYS = ("FY2023", "FY2023Q1", "FY2023Q2", "FY2023Q3", "FY2023Q4")


def footed(rows: dict[str, tuple[int | None, ...]]) -> dict[tuple[str, str], Cell]:
    """Hand cells from (FY, Q1, Q2, Q3, Q4) per code; None is an empty cell."""
    return {
        (code, key): (EMPTY if v is None else Cell(D(v), "reported"))
        for code, values in rows.items()
        for key, v in zip(PERIOD_KEYS, values, strict=True)
    }


def value(cells: dict[tuple[str, str], Cell], code: str, key: str) -> Decimal | None:
    return cells.get((code, key), EMPTY).value


def opex_gap(cells: dict[tuple[str, str], Cell], key: str) -> Decimal:
    """gross profit - sga (0 when empty) - residual - operating income: 0 when it foots."""
    gp, other, oi = (
        value(cells, c, key)
        for c in ("gross_profit", "other_operating_expenses", "operating_income")
    )
    assert gp is not None and other is not None and oi is not None
    return gp - (value(cells, "sga", key) or 0) - other - oi


# sga is reported in Q1..Q3 but not in Q4: its Q4 is hidden inside the residual (150 = 100 + 50)
SGA_HIDDEN_IN_Q4 = {
    "gross_profit": (800, 200, 200, 200, 200),
    "sga": (300, 100, 100, 100, None),
    "other_operating_expenses": (300, 50, 50, 50, 150),
    "operating_income": (200, 50, 50, 50, 50),
    "pretax_income": (200, 50, 50, 50, 50),
}


def test_an_empty_q4_line_still_rolls_up_and_its_residual_absorbs_the_delta() -> None:
    cells = footed(SGA_HIDDEN_IN_Q4)

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", -5)], calendar())

    assert value(out, "sga", "FY2023") == 295
    assert value(out, "sga", "FY2023Q4") is None  # no value invented on the line
    assert ("sga", "FY2023Q4") not in applied
    assert value(out, "operating_income", "FY2023Q4") == 55  # expense removed: profit up
    assert value(out, "pretax_income", "FY2023Q4") == 55
    assert value(out, "other_operating_expenses", "FY2023Q4") == 145  # the opposite delta
    assert value(out, "other_operating_expenses", "FY2023") == 300  # the year is the own period
    via_sga = [AppliedAdjustment(1, "sga", D(-5), "sga")]
    for code in ("operating_income", "pretax_income", "other_operating_expenses"):
        assert applied[(code, "FY2023Q4")] == via_sga, code
    quarters = [value(out, "operating_income", f"FY2023Q{n}") for n in (1, 2, 3, 4)]
    assert sum(v for v in quarters if v is not None) == value(out, "operating_income", "FY2023")
    for key in PERIOD_KEYS:  # components + residual = subtotal, in every column
        assert opex_gap(out, key) == 0, key


def test_an_empty_year_line_still_rolls_up_and_the_year_residual_absorbs_the_delta() -> None:
    cells = footed(
        {
            "gross_profit": (800, 200, 200, 200, 200),
            "sga": (None, 100, 100, 100, 100),  # the year is hidden inside its residual (600)
            "other_operating_expenses": (600, 50, 50, 50, 50),
            "operating_income": (200, 50, 50, 50, 50),
        }
    )

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "Q2", -5)], calendar())

    assert value(out, "sga", "FY2023Q2") == 95
    assert value(out, "sga", "FY2023") is None
    assert ("sga", "FY2023") not in applied
    assert value(out, "operating_income", "FY2023") == 205
    assert value(out, "other_operating_expenses", "FY2023") == 595
    assert applied[("other_operating_expenses", "FY2023")] == [
        AppliedAdjustment(1, "sga", D(-5), "sga")
    ]
    assert value(out, "other_operating_expenses", "FY2023Q2") == 50  # own period: no absorption
    quarters = [value(out, "operating_income", f"FY2023Q{n}") for n in (1, 2, 3, 4)]
    assert sum(v for v in quarters if v is not None) == value(out, "operating_income", "FY2023")
    for key in PERIOD_KEYS:
        assert opex_gap(out, key) == 0, key


def test_a_q4_adjustment_on_a_line_with_an_empty_year_lands_on_the_year_residual() -> None:
    cells = footed({**SGA_HIDDEN_IN_Q4, "sga": (None, 100, 100, 100, 100)})
    cells[("other_operating_expenses", "FY2023")] = Cell(D(600), "reported")
    cells[("other_operating_expenses", "FY2023Q4")] = Cell(D(50), "reported")

    out, _ = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "Q4", 3)], calendar())

    assert value(out, "sga", "FY2023") is None
    assert value(out, "operating_income", "FY2023") == 197
    assert value(out, "other_operating_expenses", "FY2023") == 603
    assert opex_gap(out, "FY2023") == 0 and opex_gap(out, "FY2023Q4") == 0


def test_without_a_residual_sibling_an_empty_paired_period_only_rolls_up() -> None:
    items = [i for i in ITEMS if i.code != "other_operating_expenses"]
    cells = footed(SGA_HIDDEN_IN_Q4)

    out, applied = apply_adjustments(cells, items, [adj(1, "sga", 2023, "FY", -5)], calendar())

    assert value(out, "operating_income", "FY2023Q4") == 55
    assert value(out, "operating_income", "FY2023") == 205
    assert value(out, "sga", "FY2023Q4") is None
    assert (
        out[("other_operating_expenses", "FY2023Q4")]
        == cells[("other_operating_expenses", "FY2023Q4")]
    )
    assert ("other_operating_expenses", "FY2023Q4") not in applied


def test_an_empty_residual_cell_stays_empty_when_it_would_absorb_a_delta() -> None:
    cells = footed({**SGA_HIDDEN_IN_Q4, "other_operating_expenses": (300, 50, 50, 50, None)})

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", -5)], calendar())

    assert value(out, "other_operating_expenses", "FY2023Q4") is None
    assert ("other_operating_expenses", "FY2023Q4") not in applied
    assert value(out, "operating_income", "FY2023Q4") == 55  # the roll-up still happens


def test_a_pretax_breakdown_line_is_absorbed_by_its_residual_sibling() -> None:
    # as in the real mapping: interest expense and the residual `other_nonoperating_income` are
    # both children of pretax_income, so the residual is the sibling that holds the missing Q4
    items = [
        *ITEMS,
        item("interest_expense", parent="pretax_income", rolls_into=[("pretax_income", -1)]),
        item(
            "other_nonoperating_income",
            parent="pretax_income",
            derive="pretax_income - operating_income + interest_expense",
            residual=True,
            rolls_into=[("pretax_income", 1)],
        ),
    ]
    cells = footed(
        {
            "operating_income": (80, 20, 20, 20, 20),
            "pretax_income": (100, 25, 25, 25, 25),
            "interest_expense": (30, 10, 10, 10, None),  # Q4 hidden in the residual
            "other_nonoperating_income": (50, 15, 15, 15, 5),
        }
    )

    out, applied = apply_adjustments(
        cells, items, [adj(1, "interest_expense", 2023, "FY", 4)], calendar()
    )

    assert value(out, "interest_expense", "FY2023Q4") is None
    assert value(out, "pretax_income", "FY2023Q4") == 21  # more expense: profit down
    assert value(out, "other_nonoperating_income", "FY2023Q4") == 1
    assert applied[("other_nonoperating_income", "FY2023Q4")] == [
        AppliedAdjustment(1, "interest_expense", D(4), "interest_expense")
    ]
    q4 = [value(out, c, "FY2023Q4") for c in ("pretax_income", "operating_income")]
    assert q4[0] is not None and q4[1] is not None
    assert q4[0] - q4[1] == value(out, "other_nonoperating_income", "FY2023Q4")  # + 0 interest


def test_a_subtotal_adjustment_with_an_empty_pair_is_absorbed_by_no_residual() -> None:
    # operating_income is no child of total_operating_costs: the residual whose formula mentions
    # it (other_operating_expenses) must not take the delta, the roll-up is all that happens
    cells = footed(
        {**SGA_HIDDEN_IN_Q4, "operating_income": (200, 50, 50, 50, None)},
    )

    out, applied = apply_adjustments(
        cells, ITEMS, [adj(1, "operating_income", 2023, "FY", 5)], calendar()
    )

    assert value(out, "operating_income", "FY2023Q4") is None
    assert value(out, "pretax_income", "FY2023Q4") == 55  # the roll-up still happens
    assert (
        out[("other_operating_expenses", "FY2023Q4")]
        == cells[("other_operating_expenses", "FY2023Q4")]
    )
    assert ("other_operating_expenses", "FY2023Q4") not in applied


def test_an_absorber_entered_by_another_adjustment_keeps_its_typed_value() -> None:
    # the residual is empty everywhere: the user types it (FY 40, and so Q4 40); there is nothing
    # reported to foot against, so the sga delta must not change the typed Q4
    cells = footed({**SGA_HIDDEN_IN_Q4, "other_operating_expenses": (None, None, None, None, None)})

    out, applied = apply_adjustments(
        cells,
        ITEMS,
        [adj(1, "sga", 2023, "FY", -5), adj(2, "other_operating_expenses", 2023, "FY", 40)],
        calendar(),
    )

    assert value(out, "other_operating_expenses", "FY2023") == 40
    assert value(out, "other_operating_expenses", "FY2023Q4") == 40
    assert applied[("other_operating_expenses", "FY2023Q4")] == [
        AppliedAdjustment(2, "other_operating_expenses", D(40), None)
    ]


def test_a_residual_is_not_rolled_up_twice_when_it_absorbs_a_delta() -> None:
    cells = footed(SGA_HIDDEN_IN_Q4)

    out, _ = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "FY", -5)], calendar())

    # the residual rolls into operating income too: a second roll-up would move it by 10
    assert value(out, "operating_income", "FY2023Q4") == 55


def test_a_line_with_no_value_in_the_users_period_is_entered_in_its_pair_too() -> None:
    # sga is empty in Q2 and in the year: the amount is the line's only value, so the year takes
    # it as well and the totals keep Q1..Q4 = FY and their residual footing
    cells = empty_at(hand_cells("sga", "operating_income"), ("sga", "FY2023Q2"), ("sga", "FY2023"))

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "sga", 2023, "Q2", 4)], calendar())

    assert out[("sga", "FY2023Q2")].value == 4 and out[("sga", "FY2023")].value == 4
    assert ("sga", "FY2023") in applied
    assert out[("operating_income", "FY2023Q2")].value == 96
    assert out[("operating_income", "FY2023")].value == 96


def test_an_instant_adjustment_on_fy_sets_both_balances_even_when_q4_is_empty() -> None:
    cells = empty_at(hand_cells("cash"), ("cash", "FY2023Q4"))

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "cash", 2023, "FY", 7)], calendar())

    assert out[("cash", "FY2023")].value == 107
    assert out[("cash", "FY2023Q4")].value == 7
    assert ("cash", "FY2023Q4") in applied


def test_an_instant_adjustment_on_q4_sets_both_balances_even_when_fy_is_empty() -> None:
    cells = empty_at(hand_cells("cash"), ("cash", "FY2023"))

    out, applied = apply_adjustments(cells, ITEMS, [adj(1, "cash", 2023, "Q4", 7)], calendar())

    assert out[("cash", "FY2023Q4")].value == 107
    assert out[("cash", "FY2023")].value == 7
    assert ("cash", "FY2023") in applied


def test_stale_adjustments_are_ignored() -> None:
    cells = hand_cells("sga", "eps_diluted")
    stale = [
        adj(1, "sga", 2019, "FY", -5),  # a period outside the calendar
        adj(2, "nowhere", 2023, "FY", -5),  # a code that no longer exists
        adj(3, "eps_diluted", 2023, "FY", -5),  # not adjustable
        adj(4, "sga", 2023, "Q9", -5),  # not a period
    ]

    out, applied = apply_adjustments(cells, ITEMS, stale, calendar())

    assert out == cells and applied == {}


def test_an_empty_frame_with_adjustments_builds_nothing() -> None:
    empty = pd.DataFrame(columns=FRAME.columns)

    result = build_statement(
        empty, ITEMS, "IS", "annual", adjustments=[adj(1, "sga", 2023, "FY", 1)]
    )  # type: ignore[arg-type]

    assert result.periods == [] and all(not r.values for r in result.rows)


def test_rows_say_which_lines_can_be_adjusted() -> None:
    income = table("IS", "annual")

    flags = {r.code: r.adjustable for r in income.rows}
    assert flags["sga"] and flags["revenue"] and flags["other_operating_expenses"]
    assert not flags["total_operating_costs"] and not flags["eps_diluted"]
    assert not flags["shares_diluted"]


# --- identity-solved cells (docs/erd/data.md "R1: identities", "Normalized view") ----------

SUM = IdentityDef("sum", "x = y + z", ((1, "x"), (-1, "y"), (-1, "z")), {"z": EXACT})


def solved_table(freq: str, *adjustments: Adj) -> StatementTable:
    """x = y + z, with z empty as reported: the identity solves it. No line rolls into another,
    so an adjustment to y reaches z only through the re-solve."""
    items = [item("x"), item("y"), item("z")]
    maps = mappings(("x", "X", 0), ("y", "Y", 0))
    quarters = {2023: (10 * B,) * 4}
    canonical = map_facts(
        select_vintage(facts([*flow_facts("X", quarters), *flow_facts("Y", {2023: (4 * B,) * 4})])),
        maps,
        items,
    )  # type: ignore[arg-type]
    return build_statement(
        canonical, items, "IS", freq, adjustments=adjustments, rules=Rules((SUM,))
    )


def z_row(table: StatementTable) -> dict[str, tuple[Decimal | None, str | None]]:
    (z,) = [r for r in table.rows if r.code == "z"]
    keys = [p.key for p in table.periods]
    return dict(zip(keys, zip(z.values, z.provenance, strict=True), strict=True))


def test_an_adjustment_to_an_operand_re_solves_an_exact_cell() -> None:
    reported = z_row(solved_table("quarterly"))
    adjusted = z_row(solved_table("quarterly", adj(1, "y", 2023, "Q2", B)))

    assert reported["FY2023Q2"] == (6 * B, "derived")
    assert adjusted["FY2023Q2"] == (5 * B, "normalized")  # x - (y + 1 B)
    assert adjusted["FY2023Q1"] == reported["FY2023Q1"]


def test_the_quarters_of_a_re_solved_flow_add_up_to_the_year() -> None:
    for adjustment in (adj(1, "y", 2023, "Q2", B), adj(2, "y", 2023, "FY", 3 * B)):
        quarterly = z_row(solved_table("quarterly", adjustment))
        year = z_row(solved_table("annual", adjustment))["FY2023"][0]

        parts = [quarterly[f"FY2023Q{n}"][0] for n in (1, 2, 3, 4)]
        assert year is not None and None not in parts
        assert sum(parts) == year  # type: ignore[arg-type]
        assert year == 24 * B - (B if adjustment.fiscal_period == "Q2" else 3 * B)


def test_an_adjustment_that_touches_no_operand_leaves_the_solved_cell_alone() -> None:
    other = adj(1, "x", 2022, "Q2", B)  # a period the company does not have

    assert z_row(solved_table("quarterly", other)) == z_row(solved_table("quarterly"))


def test_an_inferred_zero_stays_zero_when_an_operand_is_adjusted() -> None:
    items = [
        item("revenue"),
        item("total_equity", "BS", kind="instant"),
        item("equity_parent", "BS", kind="instant"),
        item("nci", "BS", kind="instant"),
    ]
    maps = mappings(
        ("revenue", "Revenues", 0),
        ("total_equity", "EquityIncl", 0),
        ("equity_parent", "Equity", 0),
    )
    equity = IdentityDef(
        "equity",
        "total_equity = equity_parent + nci",
        ((1, "total_equity"), (-1, "equity_parent"), (-1, "nci")),
        {"nci": SolveRule("zero_only", None)},
    )
    balances = (50 * B, 60 * B, 70 * B, 80 * B)
    canonical = map_facts(
        select_vintage(
            facts(
                [
                    *flow_facts("Revenues", {2023: (B,) * 4}),
                    *instant_facts("EquityIncl", {2023: balances}),
                    *instant_facts("Equity", {2023: balances}),
                ]
            )
        ),
        maps,
        items,
    )  # type: ignore[arg-type]

    table = build_statement(
        canonical,
        items,
        "BS",
        "annual",
        adjustments=[adj(1, "equity_parent", 2023, "FY", 5 * B)],
        rules=Rules((equity,)),
    )

    (nci,) = [r for r in table.rows if r.code == "nci"]
    assert nci.values == [0]
    assert nci.provenance == ["zero_inferred"]
