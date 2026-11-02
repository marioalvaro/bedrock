"""The Tier 1 driver model on a synthetic company, hand-computed (docs/erd/forecasting.md
"Tier 1 driver model (M4)")."""

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from bedrock.forecast.drivers import DriverKind, drivers_for
from bedrock.forecast.engines.driver import DriverModel, ForecastStatements, Horizon
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import (
    FLAT,
    Default,
    ForecastHistory,
    ScenarioSettings,
    SeriesHistory,
    scenario_drivers,
)
from bedrock.forecast.resolve import DriverRow, Resolved, resolve_drivers
from tests.forecast_data import make_history, resolved

D = Decimal
GROWTH = ScenarioSettings("growth")

# FY2025, the opening of an annual-only, calendar-year company. Balance sheet:
#   assets 100 + 50 + 80 + 40 + 30 = 300 current; 400 + 20 + 100 + 30 + 100 + 50 = 700
#   non-current; 1000 in total.
#   liabilities 60 + 40 + 20 + 30 + 50 = 200 current; 200 + 20 + 80 = 300 non-current; 500.
#   equity 150 + 250 - 10 + 10 = 400 parent + 100 NCI = 500; L + E = 1000.
OPENING_BS = {
    "cash": 100,
    "short_term_investments": 50,
    "receivables": 80,
    "inventory": 40,
    "other_current_assets": 30,
    "total_current_assets": 300,
    "ppe_net": 400,
    "operating_lease_rou": 20,
    "goodwill": 100,
    "intangibles": 30,
    "long_term_investments": 100,
    "other_noncurrent_assets": 50,
    "total_noncurrent_assets": 700,
    "total_assets": 1000,
    "accounts_payable": 60,
    "short_term_debt": 40,
    "deferred_revenue_current": 20,
    "accrued_liabilities": 30,
    "other_current_liabilities": 50,
    "total_current_liabilities": 200,
    "long_term_debt": 200,
    "operating_lease_liabilities_noncurrent": 20,
    "other_noncurrent_liabilities": 80,
    "total_noncurrent_liabilities": 300,
    "total_liabilities": 500,
    "common_stock_apic": 150,
    "retained_earnings": 250,
    "aoci": -10,
    "other_equity": 10,
    "equity_parent": 400,
    "nci": 100,
    "total_equity": 500,
    "total_liabilities_and_equity": 1000,
    "total_debt": 240,
    "shares_outstanding": 100,
}
OPENING_IS = {"revenue": 1000, "shares_diluted": 105, "shares_basic": 100}

# The FY2026 drivers; FY2026 has 365 days, so f = 1.
DRIVERS_2026: dict[str, Any] = {
    "revenue_growth": "0.10",
    "gross_margin": "0.40",
    "rnd_pct_revenue": "0.05",
    "sga_pct_revenue": "0.10",
    "other_opex_pct_revenue": "0.02",
    "d_and_a_pct_revenue": "0.05",
    "sbc_pct_revenue": "0.02",
    "other_nonoperating_pct_revenue": "0.01",
    "interest_rate": "0.05",
    "tax_rate": "0.25",
    "nci_share": "0.10",
    "receivable_days": "36.5",
    "inventory_days": "73",
    "payable_days": "36.5",
    "capex_pct_revenue": "0.08",
    "debt_issued": 30,
    "debt_repaid": 50,
    "min_cash": 50,
    "buybacks": 40,
    "dividend_payout": "0.20",
    "share_change": "-0.02",
}


def annual_company(**overrides: Any) -> ForecastHistory:
    bs = {**OPENING_BS, **overrides}
    return make_history({2024: {"revenue": 900}, 2025: {**OPENING_IS, **bs}})


def run(
    history: ForecastHistory,
    by_year: Mapping[int, Mapping[str, Any]],
    quarters: int = 4,
    settings: ScenarioSettings = GROWTH,
    codes: list[str] | None = None,
) -> ForecastStatements:
    return DriverModel().run(
        history, resolved(by_year, codes), Horizon(len(by_year), quarters), settings
    )


def values(out: ForecastStatements, key: str, codes: list[str]) -> dict[str, Decimal | None]:
    return {code: out.get(code, key) for code in codes}


def test_one_annual_year_income_statement() -> None:
    out = run(annual_company(), {2026: DRIVERS_2026})
    assert [(p.key, p.label) for p in out.periods] == [("FY2026", "FY26E")]
    assert values(out, "FY2026", list(EXPECTED_IS)) == EXPECTED_IS


EXPECTED_IS = {
    "revenue": D(1100),  # 1000 × 1.10
    "cost_of_revenue": D(660),  # 1100 × (1 - 0.40)
    "gross_profit": D(440),
    "rnd": D(55),  # 1100 × 0.05
    "sga": D(110),
    "other_operating_expenses": D(22),
    "total_operating_costs": D(187),
    "operating_income": D(253),  # 440 - 187
    "interest_expense": D(12),  # 0.05 × opening total debt (40 + 200) × 365 / 365
    "other_nonoperating_income": D(11),
    "pretax_income": D(252),  # 253 - 12 + 11
    "income_tax": D(63),
    "net_income": D(189),
    "net_income_nci": D("18.9"),
    "net_income_common": D("170.1"),
    "shares_diluted": D("102.9"),  # 105 × 0.98
    "shares_basic": D(98),  # 100 × 0.98
    "eps_diluted": D("170.1") / D("102.9"),
    "eps_basic": D("170.1") / D(98),
    "dividends_per_share": D("34.02") / D(98),  # dividends 0.20 × 170.1
    "goodwill_impairment": None,
}


def test_one_annual_year_balance_sheet() -> None:
    out = run(annual_company(), {2026: DRIVERS_2026})
    assert values(out, "FY2026", list(EXPECTED_BS)) == EXPECTED_BS


EXPECTED_BS = {
    "cash": D("67.98"),  # 100 + net change in cash -32.02; above min cash 50, no revolver
    "short_term_investments": D(50),
    "receivables": D(110),  # 1100 × 36.5 / 365
    "inventory": D(132),  # 660 × 73 / 365
    "other_current_assets": D(30),
    "total_current_assets": D("389.98"),
    "ppe_net": D(433),  # 400 + capex 88 - D&A 55
    "operating_lease_rou": D(20),
    "goodwill": D(100),
    "intangibles": D(30),
    "long_term_investments": D(100),
    "other_noncurrent_assets": D(50),
    "total_noncurrent_assets": D(733),
    "total_assets": D("1122.98"),
    "accounts_payable": D(66),  # 660 × 36.5 / 365
    "short_term_debt": D(40),
    "deferred_revenue_current": D(20),
    "accrued_liabilities": D(30),
    "other_current_liabilities": D(50),
    "total_current_liabilities": D(206),
    "long_term_debt": D(180),  # 200 + 30 - 50
    "operating_lease_liabilities_noncurrent": D(20),
    "other_noncurrent_liabilities": D(80),
    "total_noncurrent_liabilities": D(280),
    "total_liabilities": D(486),
    "temporary_equity": D(0),
    "common_stock_apic": D(172),  # 150 + SBC 22
    "retained_earnings": D("346.08"),  # 250 + 170.1 - 34.02 - 40
    "aoci": D(-10),
    "other_equity": D(10),
    "equity_parent": D("518.08"),
    "nci": D("118.9"),  # 100 + 18.9
    "total_equity": D("636.98"),
    "total_liabilities_and_equity": D("1122.98"),  # 486 + 0 + 636.98
    "total_debt": D(220),
    "net_debt": D("102.02"),  # 220 - 67.98 - 50
    "shares_outstanding": D(98),
    "shares_issued": None,
    "treasury_shares": None,
}


def test_one_annual_year_cash_flow() -> None:
    out = run(annual_company(), {2026: DRIVERS_2026})
    assert values(out, "FY2026", list(EXPECTED_CF)) == EXPECTED_CF


EXPECTED_CF = {
    "cf_net_income": D(189),
    "d_and_a": D(55),
    "sbc": D(22),
    "deferred_taxes": D(0),
    "change_receivables": D(-30),  # -(110 - 80)
    "change_inventory": D(-92),  # -(132 - 40)
    "change_payables": D(6),  # 66 - 60
    "other_operating_activities": D(0),
    "cfo": D(150),
    "capex": D(-88),
    "acquisitions": D(0),
    "purchases_of_investments": D(0),
    "sales_maturities_of_investments": D(0),
    "other_investing_activities": D(0),
    "cfi": D(-88),
    "debt_issued": D(30),
    "debt_repaid": D(-50),
    "buybacks": D(-40),
    "dividends_paid": D("-34.02"),
    "other_financing_activities": D(0),
    "cff": D("-94.02"),
    "fx_effect": D(0),
    "net_change_in_cash": D("-32.02"),  # 150 - 88 - 94.02
    "free_cash_flow": D(62),  # 150 - 88
}


def test_every_period_passes_its_integrity_checks() -> None:
    out = run(annual_company(), {2026: DRIVERS_2026})
    assert [(c.period_key, c.ok, c.quarters_diff) for c in out.integrity] == [
        ("FY2026", True, None)
    ]
    assert out.warnings == ()


def test_the_revolver_draws_below_min_cash_and_repays_later() -> None:
    # FY2026 as above but min cash 100: cash before the plug is 67.98, so the revolver draws
    # 32.02. FY2027: no growth (working capital unchanged), no payout, buybacks or debt flows;
    # interest 0.05 × opening total debt (72.02 + 180) = 12.601; pretax 253 - 12.601 + 11 =
    # 251.399; tax 62.84975; NI 188.54925; CFO 188.54925 + 55 + 22 = 265.54925; CFI -88;
    # cash before the plug 100 + 177.54925 = 277.54925, so the revolver repays all 32.02.
    fy2027 = {
        **DRIVERS_2026,
        "revenue_growth": 0,
        "dividend_payout": 0,
        "buybacks": 0,
        "debt_issued": 0,
        "debt_repaid": 0,
        "share_change": 0,
        "min_cash": 100,
    }
    out = run(annual_company(), {2026: {**DRIVERS_2026, "min_cash": 100}, 2027: fy2027})
    assert values(out, "FY2026", ["cash", "short_term_debt", "debt_issued", "cff"]) == {
        "cash": D(100),
        "short_term_debt": D("72.02"),
        "debt_issued": D("62.02"),  # 30 + 32.02
        "cff": D(-62),  # 62.02 - 50 - 40 - 34.02
    }
    assert out.get("net_change_in_cash", "FY2026") == 0
    assert values(out, "FY2027", ["interest_expense", "net_income", "cash", "short_term_debt"]) == {
        "interest_expense": D("12.601"),
        "net_income": D("188.54925"),
        "cash": D("245.52925"),  # 277.54925 - 32.02
        "short_term_debt": D(40),
    }
    assert out.get("debt_repaid", "FY2027") == D("-32.02")
    assert all(c.ok for c in out.integrity)


def test_debt_repaid_is_capped_at_the_opening_long_term_debt() -> None:
    out = run(annual_company(), {2026: {**DRIVERS_2026, "debt_repaid": 500}})
    assert out.get("debt_repaid", "FY2026") == D(-200)
    assert out.get("long_term_debt", "FY2026") == D(30)  # 200 + 30 - 200
    assert out.warnings == ("FY26E: debt_repaid is capped at the opening long-term debt",)


def test_a_flat_working_capital_driver_holds_the_opening_line() -> None:
    out = run(annual_company(), {2026: {**DRIVERS_2026, "receivable_days": FLAT}})
    assert out.get("receivables", "FY2026") == D(80)
    assert out.get("change_receivables", "FY2026") == D(0)
    assert out.get("inventory", "FY2026") == D(132)


def test_a_loss_pays_no_dividends() -> None:
    # gross margin 0.05: gross profit 55, operating income 55 - 187 = -132, pretax -132 - 12 +
    # 11 = -133, tax -33.25, NI -99.75, NCI -9.975, NI common -89.775.
    out = run(annual_company(), {2026: {**DRIVERS_2026, "gross_margin": "0.05"}})
    assert out.get("net_income_common", "FY2026") == D("-89.775")
    assert out.get("dividends_paid", "FY2026") == D(0)
    assert out.get("dividends_per_share", "FY2026") == D(0)
    assert out.get("retained_earnings", "FY2026") == D("120.225")  # 250 - 89.775 - 40


def test_a_missing_share_count_is_held_at_the_latest_one() -> None:
    history = make_history(
        {
            2024: {"revenue": 900, "shares_diluted": 110},
            2025: {**OPENING_IS, **OPENING_BS, "shares_diluted": None},
        }
    )
    out = run(history, {2026: DRIVERS_2026})
    assert out.get("shares_diluted", "FY2026") == D("107.8")  # 110 × 0.98
    assert out.get("eps_diluted", "FY2026") == D("170.1") / D("107.8")


def test_no_share_count_at_all_leaves_shares_and_eps_null() -> None:
    history = make_history({2024: {"revenue": 900}, 2025: {**OPENING_BS, "revenue": 1000}})
    out = run(history, {2026: DRIVERS_2026})
    assert values(out, "FY2026", ["shares_basic", "eps_basic", "dividends_per_share"]) == {
        "shares_basic": None,
        "eps_basic": None,
        "dividends_per_share": None,
    }
    assert all(c.ok for c in out.integrity)


def test_a_missing_required_driver_makes_the_forecast_unavailable() -> None:
    drivers = resolved({2026: DRIVERS_2026})
    values_ = dict(drivers.values)
    values_[("gross_margin", 2026)] = Resolved(None, None)
    with pytest.raises(ForecastUnavailable, match="^Set these drivers: gross_margin$"):
        DriverModel().run(annual_company(), replace(drivers, values=values_), Horizon(1, 4), GROWTH)


def test_an_out_of_bounds_driver_makes_the_forecast_unavailable() -> None:
    with pytest.raises(
        ForecastUnavailable, match=r"^gross_margin must be in \[-1, 1\] \(FY2026\)$"
    ):
        run(annual_company(), {2026: {**DRIVERS_2026, "gross_margin": "1.5"}})


def series(id_: int, dimension: str, metric: str, unit: str, fy2025: int | None) -> SeriesHistory:
    values = {} if fy2025 is None else {2025: D(fy2025)}
    return SeriesHistory(id_, dimension, f"S{id_}", metric, unit, values)


def segment_run(segments: list[SeriesHistory]) -> ForecastStatements:
    history = make_history(
        {2024: {"revenue": 900}, 2025: {**OPENING_IS, **OPENING_BS}}, series=segments
    )
    settings = ScenarioSettings("segments", segment_dimension="business")
    growth = {"segment_growth:1": "0.10", "segment_growth:2": "-0.20"}
    return run(
        history,
        {2026: {**DRIVERS_2026, **growth}},
        settings=settings,
        codes=[d.code for d in scenario_drivers(history, settings)],
    )


def test_segments_grow_each_series_and_hold_the_unallocated_share() -> None:
    # FY2025: revenue 1000, segments 600 + 300 = 900, so Unallocated u = 0.1.
    # FY2026: 600 × 1.10 = 660, 300 × 0.80 = 240; R = 900 / (1 - 0.1) = 1000.
    # A geographic series and an operating-income series of the business dimension are left out.
    out = segment_run(
        [
            series(1, "business", "revenue", "USD", 600),
            series(2, "business", "revenue", "USD", 300),
            series(3, "geo", "revenue", "USD", 1000),
            series(4, "business", "operating_income", "USD", 50),
        ]
    )
    assert out.get("revenue", "FY2026") == D(1000)
    assert all(c.ok for c in out.integrity)


def test_segments_covering_all_revenue_drop_the_unallocated_share() -> None:
    # 700 + 300 = 1000 = revenue, u = 0. FY2026: 770 + 240 = 1010.
    out = segment_run(
        [series(1, "business", "revenue", "USD", 700), series(2, "business", "revenue", "USD", 300)]
    )
    assert out.get("revenue", "FY2026") == D(1010)


def test_segments_with_no_revenue_are_unavailable() -> None:
    # 0 + 0: u = (1000 - 0) / 1000 = 1.
    with pytest.raises(ForecastUnavailable, match="^The business segments have no FY2025 revenue$"):
        segment_run(
            [series(1, "business", "revenue", "USD", 0), series(2, "business", "revenue", "USD", 0)]
        )


def test_a_segment_without_a_last_year_value_is_unavailable() -> None:
    with pytest.raises(ForecastUnavailable, match="^Segment S2 has no FY2025 value$"):
        segment_run(
            [
                series(1, "business", "revenue", "USD", 600),
                series(2, "business", "revenue", "USD", None),
            ]
        )


def volume_price_run(price: int | None) -> ForecastStatements:
    kpis = [series(1, "kpi", "units", "count", 40), series(2, "kpi", "asp", "USD_per_unit", price)]
    history = make_history(
        {2024: {"revenue": 900}, 2025: {**OPENING_IS, **OPENING_BS}}, series=kpis
    )
    return run(
        history,
        {2026: {**DRIVERS_2026, "volume_growth": "0.10", "price_growth": "0.05"}},
        settings=ScenarioSettings("volume_price", volume_kpi="units", price_kpi="asp"),
        codes=[d.code for d in drivers_for("volume_price")],
    )


def test_volume_price_holds_k() -> None:
    # FY2025: revenue 1000, volume 40, price 20, so k = 1000 / (40 × 20) = 1.25.
    # FY2026: R = 1.25 × (40 × 1.10) × (20 × 1.05) = 1.25 × 44 × 21 = 1155.
    out = volume_price_run(20)
    assert out.get("revenue", "FY2026") == D(1155)
    assert all(c.ok for c in out.integrity)


def test_a_kpi_without_a_last_year_value_is_unavailable() -> None:
    with pytest.raises(ForecastUnavailable, match="^KPI asp has no FY2025 value$"):
        volume_price_run(None)


# A calendar-year company with quarters; its opening is Q2 FY2026 (Q1-Q2 actual).
QUARTERS: dict[str, dict[str, Any]] = {
    "FY2025Q1": {"revenue": 200, "shares_diluted": 100},
    "FY2025Q2": {"revenue": 250, "shares_diluted": 102},
    "FY2025Q3": {"revenue": 250, "shares_diluted": 104},
    "FY2025Q4": {"revenue": 300, "shares_diluted": 106, **OPENING_BS},
    "FY2026Q1": {"revenue": 220, "net_income": 40, "shares_diluted": 108},
    "FY2026Q2": {"revenue": 270, "net_income": 50, "shares_diluted": 110, **OPENING_BS},
}


def quarterly_company(quarters: Mapping[str, Mapping[str, Any]] = QUARTERS) -> ForecastHistory:
    return make_history({2024: {"revenue": 900}, 2025: {**OPENING_IS, **OPENING_BS}}, quarters)


def test_a_quarter_span_from_an_opening_q2_builds_its_year_from_quarters() -> None:
    out = run(quarterly_company(), {2026: DRIVERS_2026, 2027: DRIVERS_2026}, quarters=2)
    assert [(p.key, p.label) for p in out.periods] == [
        ("FY2026Q3", "Q3 FY26E"),
        ("FY2026Q4", "Q4 FY26E"),
        ("FY2026", "FY26E"),
        ("FY2027", "FY27E"),
    ]
    assert [p.key for p in out.quarterly()] == ["FY2026Q3", "FY2026Q4"]
    # Each quarter grows the same quarter last year by the year's implied growth (1.10).
    assert out.get("revenue", "FY2026Q3") == D(275)  # 250 × 1.10
    assert out.get("revenue", "FY2026Q4") == D(330)  # 300 × 1.10
    # The year adds its actual quarters: 220 + 270 + 275 + 330.
    assert out.get("revenue", "FY2026") == D(1095)
    net = out.get("net_income", "FY2026Q3"), out.get("net_income", "FY2026Q4")
    assert net[0] is not None and net[1] is not None
    assert out.get("net_income", "FY2026") == 40 + 50 + net[0] + net[1]
    # Instants are Q4's; average shares the mean of the four quarters.
    assert out.get("cash", "FY2026") == out.get("cash", "FY2026Q4")
    q3, q4 = D(104) * D("0.98"), D(106) * D("0.98")
    assert out.get("shares_diluted", "FY2026Q3") == q3
    assert out.get("shares_diluted", "FY2026") == (108 + 110 + q3 + q4) / 4
    # A quarter's interest accrues for its days (Q3: 92) on its opening debt (40 + 200).
    assert out.get("interest_expense", "FY2026Q3") == D("0.05") * 240 * 92 / 365
    # A quarter takes a quarter of the year's amounts: 200 + 30 / 4 - 50 / 4.
    assert out.get("long_term_debt", "FY2026Q3") == D(195)
    # The year after the span runs on the annual model.
    assert out.get("revenue", "FY2027") == D(1095) * D("1.10")
    assert out.opening.year_to_date["revenue"] == D(490)
    assert [(c.period_key, c.quarters_diff, c.ok) for c in out.integrity] == [
        ("FY2026Q3", None, True),
        ("FY2026Q4", None, True),
        ("FY2026", D(0), True),
        ("FY2027", None, True),
    ]


def test_an_opening_q4_builds_the_next_year_from_four_forecast_quarters() -> None:
    quarters = {k: v for k, v in QUARTERS.items() if k.startswith("FY2025")}
    out = run(quarterly_company(quarters), {2026: DRIVERS_2026, 2027: DRIVERS_2026})
    assert [p.key for p in out.periods] == [
        "FY2026Q1",
        "FY2026Q2",
        "FY2026Q3",
        "FY2026Q4",
        "FY2026",
        "FY2027",
    ]
    assert out.get("revenue", "FY2026") == D(1100)  # (200 + 250 + 250 + 300) × 1.10
    assert all(c.ok for c in out.integrity)


def test_the_span_extends_to_the_end_of_its_last_fiscal_year() -> None:
    by_year = {2026: DRIVERS_2026, 2027: DRIVERS_2026, 2028: DRIVERS_2026}
    out = run(quarterly_company(), by_year, quarters=4)
    # Q3, Q4 FY26 and Q1, Q2 FY27, extended to Q4 FY27.
    assert [p.key for p in out.quarterly()][-1] == "FY2027Q4"
    assert len(out.quarterly()) == 6
    assert [p.key for p in out.annual()] == ["FY2026", "FY2027", "FY2028"]
    assert all(c.ok for c in out.integrity)


def test_a_quarter_without_last_year_revenue_is_unavailable() -> None:
    quarters = {**QUARTERS, "FY2025Q3": {"revenue": None}}
    with pytest.raises(ForecastUnavailable, match="^No quarterly history for Q3 FY25$"):
        run(quarterly_company(quarters), {2026: DRIVERS_2026, 2027: DRIVERS_2026}, quarters=2)


def test_an_annual_only_company_has_no_quarterly_forecast() -> None:
    out = run(annual_company(), {2026: DRIVERS_2026})
    with pytest.raises(ForecastUnavailable, match="^No quarterly history$"):
        out.quarterly()


def test_an_unbalanced_opening_is_unavailable() -> None:
    # Total assets 2,000,000 above liabilities and equity: past the 1,000,000 USD floor.
    with pytest.raises(
        ForecastUnavailable,
        match=r"^The FY25 balance sheet does not balance \(difference 2000000\)$",
    ):
        run(annual_company(total_assets=2_001_000), {2026: DRIVERS_2026})


def test_an_opening_difference_within_tolerance_goes_to_other_noncurrent_assets() -> None:
    # Cash 105 and total assets 1005: 5 above liabilities and equity, within tolerance; 50 - 5.
    out = run(annual_company(cash=105, total_assets=1005), {2026: DRIVERS_2026})
    assert out.opening.balance["other_noncurrent_assets"] == D(45)
    assert out.get("other_noncurrent_assets", "FY2026") == D(45)
    assert all(c.ok for c in out.integrity)


def test_missing_lines_go_to_the_catch_all_line_of_their_section() -> None:
    # An unclassified sheet (DE): the reported totals balance but some lines are null (0).
    #   assets: ppe_net null, leaves 1000 - 400 = 600; other_noncurrent_assets 50 + 400 = 450.
    #   liabilities: accounts_payable and other_noncurrent_liabilities null, leaves 360;
    #   other_noncurrent_liabilities 500 - 360 = 140.
    #   parent equity: aoci null, leaves 410; other_equity 10 + (400 - 410) = 0.
    out = run(
        annual_company(
            ppe_net=None, accounts_payable=None, other_noncurrent_liabilities=None, aoci=None
        ),
        {2026: DRIVERS_2026},
    )
    opening = out.opening.balance
    assert (opening["ppe_net"], opening["other_noncurrent_assets"]) == (D(0), D(450))
    assert (opening["accounts_payable"], opening["other_noncurrent_liabilities"]) == (0, D(140))
    assert (opening["aoci"], opening["other_equity"]) == (D(0), D(0))
    assert all(c.ok for c in out.integrity)


def test_quarters_without_a_fiscal_year_are_unavailable() -> None:
    history = make_history({}, {"FY2026Q1": {**OPENING_IS, **OPENING_BS}})
    with pytest.raises(ForecastUnavailable, match="^No fiscal year to start from$"):
        DriverModel().run(history, resolved({2026: DRIVERS_2026}), Horizon(1, 4), GROWTH)


# --- quarter drivers (docs/erd/forecasting.md "Quarterly drivers" -> Model) ---------------------


def quarter_run(
    own: list[DriverRow],
    base: list[DriverRow] | None = None,
    history: ForecastHistory | None = None,
    settings: ScenarioSettings = GROWTH,
    extra: Mapping[str, str] | None = None,
    is_base: bool = True,
) -> ForecastStatements:
    """FY2026 Q3-Q4 (the opening is Q2 FY2026) and FY2027 on the DRIVERS_2026 defaults, with the
    given quarter rows (and `extra` default drivers)."""
    history = history or quarterly_company()
    defaults: dict[str, Default] = {
        code: D(str(value)) for code, value in {**DRIVERS_2026, **(extra or {})}.items()
    }
    if settings.revenue_method != "growth":
        defaults = {d.code: defaults[d.code] for d in scenario_drivers(history, settings)}
    years = [2026, 2027]
    drivers = resolve_drivers(base or [], own, defaults, years, is_base)
    return DriverModel().run(history, drivers, Horizon(2, 2), settings)


NEAR = D("1E-20")  # Decimal division rounds at 28 digits


def near(value: Decimal | None, expected: Decimal) -> bool:
    return value is not None and abs(value - expected) < NEAR


def qrow(
    code: str, period: str, value: str, year: int = 2026, kind: DriverKind = "value"
) -> DriverRow:
    return DriverRow(code, year, kind, D(value), period)


def test_quarter_rows_absent_gives_the_same_statements_as_before() -> None:
    explicit = run(quarterly_company(), {2026: DRIVERS_2026, 2027: DRIVERS_2026}, quarters=2)
    assert quarter_run([]).values == explicit.values


def test_a_quarter_revenue_growth_grows_the_same_quarter_last_year_by_it() -> None:
    out = quarter_run([qrow("revenue_growth", "Q3", "0.20")])
    assert out.get("revenue", "FY2026Q3") == D(300)  # 250 × 1.20
    assert out.get("revenue", "FY2026Q4") == D(330)  # 300 × 1.10, the year's growth
    assert out.get("revenue", "FY2026") == D(1120)  # 220 + 270 + 300 + 330
    assert out.get("revenue", "FY2027") == D(1120) * D("1.10")
    assert all(c.ok for c in out.integrity)
    assert (
        "FY2026 is built from its quarters: its quarter drivers, not the annual revenue_growth, "
        "set its revenue"
    ) in out.warnings


def test_a_quarter_value_equal_to_its_year_makes_no_warning() -> None:
    out = quarter_run([qrow("revenue_growth", "Q3", "0.10"), qrow("gross_margin", "Q3", "0.1")])
    assert not [w for w in out.warnings if "built from its quarters" in w]


def test_a_quarter_buyback_replaces_a_quarter_of_the_year_in_that_quarter_only() -> None:
    out = quarter_run([qrow("buybacks", "Q3", "100")])
    assert out.get("buybacks", "FY2026Q3") == D(-100)
    assert out.get("buybacks", "FY2026Q4") == D(-10)  # the year's 40 / 4
    assert out.get("buybacks", "FY2026") == D(-110)  # the quarters' sum, not the annual driver
    assert out.get("buybacks", "FY2027") == D(-40)
    # RE rolls forward with the quarter's amount: Q3 opening RE + NI common - dividends - 100
    q3 = out.get("retained_earnings", "FY2026Q3")
    rolled = (
        D(250)
        + (out.get("net_income_common", "FY2026Q3") or 0)
        + (out.get("dividends_paid", "FY2026Q3") or 0)
        - 100
    )
    assert q3 is not None and abs(q3 - rolled) < NEAR
    assert any("buybacks" in w and "built from its quarters" in w for w in out.warnings)
    assert all(c.ok for c in out.integrity)


def test_a_quarter_gross_margin_moves_that_quarter_only() -> None:
    out = quarter_run([qrow("gross_margin", "Q4", "0.30")])
    assert out.get("cost_of_revenue", "FY2026Q3") == D(275) * D("0.60")  # the year's 0.40
    assert out.get("cost_of_revenue", "FY2026Q4") == D(330) * D("0.70")
    assert not [w for w in out.warnings if "built from its quarters" in w]  # not a revenue driver


def test_a_quarter_share_change_is_over_the_same_quarter_last_year() -> None:
    out = quarter_run([qrow("share_change", "Q3", "-0.10")])
    assert out.get("shares_diluted", "FY2026Q3") == D(104) * D("0.90")
    assert out.get("shares_diluted", "FY2026Q4") == D(106) * D("0.98")


def test_a_quarter_tax_rate_and_interest_rate_apply_to_that_quarter() -> None:
    out = quarter_run([qrow("interest_rate", "Q4", "0.10")])
    # Q4: 92 days on its opening debt; Q3 keeps the year's 5%
    q3_debt = out.get("total_debt", "FY2026Q3")
    assert q3_debt is not None
    assert out.get("interest_expense", "FY2026Q3") == D("0.05") * 240 * 92 / 365
    assert out.get("interest_expense", "FY2026Q4") == D("0.10") * q3_debt * 92 / 365


def test_an_offset_scenario_with_an_annual_offset_forecasts_as_the_year_did() -> None:
    base = quarter_run([])
    bull = quarter_run(
        [
            DriverRow("gross_margin", 2026, "offset", D("0.03")),
            DriverRow("gross_margin", 2027, "offset", D("0.03")),
        ],
        is_base=False,
    )
    assert bull.get("gross_profit", "FY2026Q3") == D(275) * D("0.43")  # 0.40 + 0.03
    assert (base.get("revenue", "FY2026Q3"), base.get("revenue", "FY2027")) == (
        bull.get("revenue", "FY2026Q3"),
        bull.get("revenue", "FY2027"),
    )


def quarterly_series(q3: tuple[int | None, int | None]) -> list[SeriesHistory]:
    """S1 600 and S2 300 in FY2025 (u = 0.1), with their Q3 FY2025 values."""
    values = [(600, q3[0]), (300, q3[1])]
    return [
        SeriesHistory(
            i + 1,
            "business",
            f"S{i + 1}",
            "revenue",
            "USD",
            {2025: D(fy)},
            {} if q is None else {(2025, "Q3"): D(q)},
        )
        for i, (fy, q) in enumerate(values)
    ]


def test_a_quarter_segment_growth_grows_the_segment_in_that_quarter() -> None:
    history = replace(quarterly_company(), segment_series=tuple(quarterly_series((100, 50))))
    settings = ScenarioSettings("segments", segment_dimension="business")
    extra = {"segment_growth:1": "0.10", "segment_growth:2": "-0.10"}
    plain = quarter_run([], history=history, settings=settings, extra=extra)
    # FY: (600 × 1.10 + 300 × 0.90) / 900 = 930 / 900 for every quarter with no row
    assert near(plain.get("revenue", "FY2026Q3"), D(250) * D(930) / D(900))
    out = quarter_run(
        [qrow("segment_growth:1", "Q3", "0.30")], history=history, settings=settings, extra=extra
    )
    # Q3: (100 × 1.30 + 50 × 0.90) / 150 = 175 / 150 on the company's Q3 FY2025 revenue 250
    assert near(out.get("revenue", "FY2026Q3"), D(250) * D(175) / D(150))
    assert near(out.get("revenue", "FY2026Q4"), D(300) * D(930) / D(900))
    assert all(c.ok for c in out.integrity)


def test_a_quarter_segment_override_needs_the_segments_quarter_last_year() -> None:
    history = replace(quarterly_company(), segment_series=tuple(quarterly_series((100, None))))
    settings = ScenarioSettings("segments", segment_dimension="business")
    extra = {"segment_growth:1": "0.10", "segment_growth:2": "-0.10"}
    with pytest.raises(ForecastUnavailable, match="^Segment S2 has no Q3 FY25 value$"):
        quarter_run(
            [qrow("segment_growth:1", "Q3", "0.30")],
            history=history,
            settings=settings,
            extra=extra,
        )
    # without an override no quarterly segment value is needed
    out = quarter_run([], history=history, settings=settings, extra=extra)
    assert near(out.get("revenue", "FY2026Q3"), D(250) * D(930) / D(900))


def test_a_quarter_volume_and_price_growth_grow_the_quarter() -> None:
    kpis = [series(1, "kpi", "units", "count", 40), series(2, "kpi", "asp", "USD_per_unit", 20)]
    history = replace(quarterly_company(), segment_series=tuple(kpis))
    settings = ScenarioSettings("volume_price", volume_kpi="units", price_kpi="asp")
    extra = {"volume_growth": "0.10", "price_growth": "0"}
    out = quarter_run(
        [qrow("volume_growth", "Q3", "0.30"), qrow("price_growth", "Q3", "0.05")],
        history=history,
        settings=settings,
        extra=extra,
    )
    assert out.get("revenue", "FY2026Q3") == D(250) * D("1.30") * D("1.05")
    assert out.get("revenue", "FY2026Q4") == D(300) * D("1.10")
    assert all(c.ok for c in out.integrity)


def test_a_quarter_value_out_of_bounds_is_unavailable_and_names_the_quarter() -> None:
    with pytest.raises(
        ForecastUnavailable, match=r"gross_margin must be in \[-1, 1\] \(Q3 FY2026\)"
    ):
        quarter_run([qrow("gross_margin", "Q3", "1.5")])
