"""Driver history, defaults, the opening period and forecast years (docs/erd/forecasting.md
"Drivers (M4)", "Start and periods") on synthetic tables, every value hand-computed."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from bedrock.forecast.drivers import Follows
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import (
    FLAT,
    ForecastHistory,
    ScenarioSettings,
    SeriesHistory,
    default_drivers,
    forecast_years,
    historical_drivers,
    historical_quarter_drivers,
    history_quarters,
    history_years,
    opening_period,
)
from tests.forecast_data import complete_sheet, make_history

GROWTH = ScenarioSettings("growth")
D = Decimal

# One fiscal year (FY2025, 365 days) with every driver input; FY2024 gives the prior values.
FY2025 = {
    "revenue": 200,
    "gross_profit": 80,
    "cost_of_revenue": 120,
    "rnd": 20,
    "sga": 30,
    "other_operating_expenses": -4,
    "d_and_a": 10,
    "sbc": 6,
    "other_nonoperating_income": 2,
    "interest_expense": 6,
    "total_debt": 140,
    "pretax_income": 100,
    "income_tax": 21,
    "net_income": 80,
    "net_income_nci": 4,
    "net_income_common": 76,
    "receivables": 20,
    "inventory": 24,
    "accounts_payable": 12,
    "capex": -16,
    "debt_issued": 50,
    "debt_repaid": -30,
    "buybacks": -40,
    "dividends_paid": -19,
    "shares_diluted": 98,
}
FY2024 = {"revenue": 160, "total_debt": 100, "shares_diluted": 100}


def test_every_history_formula_on_one_year() -> None:
    history = make_history({2024: FY2024, 2025: FY2025})
    got = {code: v for (code, fy), v in historical_drivers(history, GROWTH).items() if fy == 2025}
    assert got == {
        "revenue_growth": D("0.25"),  # 200 / 160 - 1
        "gross_margin": D("0.4"),  # 80 / 200
        "rnd_pct_revenue": D("0.1"),  # 20 / 200
        "sga_pct_revenue": D("0.15"),  # 30 / 200
        "other_opex_pct_revenue": D("-0.02"),  # -4 / 200
        "d_and_a_pct_revenue": D("0.05"),  # 10 / 200
        "sbc_pct_revenue": D("0.03"),  # 6 / 200
        "other_nonoperating_pct_revenue": D("0.01"),  # 2 / 200
        "interest_rate": D("0.05"),  # 6 / mean(100, 140)
        "tax_rate": D("0.21"),  # 21 / 100
        "nci_share": D("0.05"),  # 4 / 80
        "receivable_days": D("36.5"),  # 20 / 200 × 365
        "inventory_days": D("73"),  # 24 / 120 × 365
        "payable_days": D("36.5"),  # 12 / 120 × 365
        "capex_pct_revenue": D("0.08"),  # -(-16) / 200
        "debt_issued": D("50"),
        "debt_repaid": D("30"),  # -(-30)
        "min_cash": None,  # a policy: no history
        "buybacks": D("40"),  # -(-40)
        "dividend_payout": D("0.25"),  # -(-19) / 76
        "share_change": D("-0.02"),  # 98 / 100 - 1
    }


def test_history_covers_the_last_five_actual_fiscal_years() -> None:
    history = make_history({fy: {"revenue": 100} for fy in range(2018, 2026)})
    assert history_years(history) == [2021, 2022, 2023, 2024, 2025]
    assert {fy for (_, fy) in historical_drivers(history, GROWTH)} == {2021, 2022, 2023, 2024, 2025}
    assert historical_drivers(history, GROWTH)[("revenue_growth", 2021)] == D(0)  # FY2020 is read


def test_a_company_with_two_years_has_two_history_years() -> None:
    history = make_history({2024: FY2024, 2025: FY2025})
    assert history_years(history) == [2024, 2025]
    # FY2023 is not there: the first year's growth has no prior.
    assert historical_drivers(history, GROWTH)[("revenue_growth", 2024)] is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"pretax_income": 0}, "tax_rate"),  # pretax <= 0
        ({"pretax_income": -10}, "tax_rate"),
        ({"net_income": 0}, "nci_share"),  # net income <= 0
        ({"net_income": -5}, "nci_share"),
        ({"net_income_common": 0}, "dividend_payout"),  # NI common <= 0
        ({"net_income_common": -1}, "dividend_payout"),
        ({"rnd": None}, "rnd_pct_revenue"),  # a missing input
        ({"income_tax": None}, "tax_rate"),
        ({"capex": None}, "capex_pct_revenue"),
        ({"debt_repaid": None}, "debt_repaid"),
        ({"total_debt": None}, "interest_rate"),
        ({"cost_of_revenue": 0}, "inventory_days"),  # a zero denominator
        ({"cost_of_revenue": None}, "payable_days"),
    ],
)
def test_null_rules(change: dict[str, int | None], code: str) -> None:
    history = make_history({2024: FY2024, 2025: {**FY2025, **change}})
    assert historical_drivers(history, GROWTH)[(code, 2025)] is None


def test_a_zero_revenue_makes_every_revenue_ratio_null() -> None:
    history = make_history({2024: FY2024, 2025: {**FY2025, "revenue": 0}})
    got = historical_drivers(history, GROWTH)
    for code in ("gross_margin", "rnd_pct_revenue", "capex_pct_revenue", "receivable_days"):
        assert got[(code, 2025)] is None, code
    assert got[("revenue_growth", 2025)] == D(-1)  # 0 / 160 - 1


def test_growth_after_a_zero_year_is_null() -> None:
    history = make_history({2024: {**FY2024, "revenue": 0}, 2025: FY2025})
    assert historical_drivers(history, GROWTH)[("revenue_growth", 2025)] is None


def test_interest_rate_is_null_when_mean_debt_is_zero() -> None:
    history = make_history({2024: {**FY2024, "total_debt": 0}, 2025: {**FY2025, "total_debt": 0}})
    assert historical_drivers(history, GROWTH)[("interest_rate", 2025)] is None
    # One side zero: the mean is half the other side.
    history = make_history({2024: {**FY2024, "total_debt": 0}, 2025: FY2025})
    assert historical_drivers(history, GROWTH)[("interest_rate", 2025)] == D(6) / D(70)


def test_days_use_the_length_of_a_53_week_year() -> None:
    # A 53-week year: 2023-10-01 to 2024-10-05 is 371 days.
    history = make_history({2024: FY2025}, dates={"FY2024": (date(2023, 10, 1), date(2024, 10, 5))})
    got = historical_drivers(history, GROWTH)
    assert got[("receivable_days", 2024)] == D("37.1")  # 20 / 200 × 371
    assert got[("inventory_days", 2024)] == D("74.2")  # 24 / 120 × 371


def _margins(*margins: str | None) -> dict[int, dict[str, int | None]]:
    """Fiscal years from 2021 with revenue 1000 and the given gross margins."""
    return {
        2021 + i: {"revenue": 1000, "gross_profit": None if m is None else int(D(m) * 1000)}
        for i, m in enumerate(margins)
    }


def test_the_default_is_the_mean_of_the_last_three_years() -> None:
    history = make_history(_margins("0.30", "0.32", "0.40", "0.42", "0.44"))
    assert default_drivers(history, GROWTH)["gross_margin"] == D("0.42")  # (0.40+0.42+0.44)/3


def test_the_default_with_fewer_than_three_years() -> None:
    history = make_history(_margins("0.40", "0.50"))
    assert default_drivers(history, GROWTH)["gross_margin"] == D("0.45")


def test_the_default_skips_a_gap_without_reaching_further_back() -> None:
    history = make_history(_margins("0.10", "0.30", "0.40", None, "0.44"))
    assert default_drivers(history, GROWTH)["gross_margin"] == D("0.42")  # (0.40+0.44)/2


def test_each_fallback_when_the_last_three_years_have_no_value() -> None:
    # Only revenue: every ratio is null, growth is 0.
    history = make_history({fy: {"revenue": 100} for fy in (2023, 2024, 2025)})
    defaults = default_drivers(history, GROWTH)
    assert defaults["revenue_growth"] == D(0)  # history exists (0, 0)
    assert defaults["gross_margin"] is None  # required
    assert defaults["tax_rate"] is None
    assert defaults["capex_pct_revenue"] is None
    assert defaults["rnd_pct_revenue"] == D(0)  # 0
    assert defaults["min_cash"] == D(0)
    assert defaults["buybacks"] == D(0)
    assert defaults["receivable_days"] is FLAT  # flat
    assert defaults["payable_days"] is FLAT
    assert defaults["d_and_a_pct_revenue"] == Follows("capex_pct_revenue", resolved=True)
    # Exactly the method's drivers.
    assert "volume_growth" not in defaults and "segment_growth" not in defaults


def test_revenue_growth_is_required_without_history() -> None:
    history = make_history({2025: {"revenue": 100}})
    assert default_drivers(history, GROWTH)["revenue_growth"] is None


def _segments() -> list[SeriesHistory]:
    return [
        SeriesHistory(7, "business", "iPhone", "revenue", "USD", {2024: D(50), 2025: D(60)}),
        SeriesHistory(3, "business", "Mac", "revenue", "USD", {2025: D(20)}),
        SeriesHistory(4, "business", "iPhone", "operating_income", "USD", {2025: D(1)}),
        SeriesHistory(5, "geo", "Americas", "revenue", "USD", {2024: D(1), 2025: D(2)}),
        SeriesHistory(8, "kpi", "Units", "units", "count", {2024: D(10), 2025: D(12)}),
        SeriesHistory(9, "kpi", "ASP", "asp", "USD_per_unit", {2024: D(4), 2025: D(5)}),
    ]


def test_segment_growth_history_and_its_fallback() -> None:
    history = make_history(
        {2023: {"revenue": 100}, 2024: {"revenue": 110}, 2025: {"revenue": 121}},
        series=_segments(),
    )
    settings = ScenarioSettings("segments", segment_dimension="business")
    got = historical_drivers(history, settings)
    assert got[("segment_growth:7", 2025)] == D("0.2")  # 60 / 50 - 1
    assert got[("segment_growth:3", 2025)] is None  # no FY2024 value
    assert "revenue_growth" not in {code for code, _ in got}
    defaults = default_drivers(history, settings)
    assert defaults["segment_growth:7"] == D("0.2")
    # Mac has no history: it follows the revenue-growth default, mean(0.1, 0.1).
    assert defaults["segment_growth:3"] == D("0.1")
    # Only revenue series of the scenario's dimension get a driver.
    assert {c for c in defaults if c.startswith("segment_growth:")} == {
        "segment_growth:7",
        "segment_growth:3",
    }


def test_segment_growth_without_any_revenue_history_is_missing() -> None:
    history = make_history({2025: {"revenue": 100}}, series=_segments())
    defaults = default_drivers(history, ScenarioSettings("segments", segment_dimension="business"))
    assert defaults["segment_growth:3"] is None


def test_volume_and_price_growth_read_the_chosen_kpis() -> None:
    history = make_history({2024: {"revenue": 1}, 2025: {"revenue": 1}}, series=_segments())
    settings = ScenarioSettings("volume_price", volume_kpi="units", price_kpi="asp")
    got = historical_drivers(history, settings)
    assert got[("volume_growth", 2025)] == D("0.2")  # 12 / 10 - 1
    assert got[("price_growth", 2025)] == D("0.25")  # 5 / 4 - 1
    # A KPI that is not there: no history, fallback 0.
    unknown = ScenarioSettings("volume_price", volume_kpi="stores", price_kpi="asp")
    assert historical_drivers(history, unknown)[("volume_growth", 2025)] is None
    assert default_drivers(history, unknown)["volume_growth"] == D(0)


def test_the_opening_is_the_latest_complete_quarter() -> None:
    history = make_history(
        {2025: {"revenue": 400}},
        quarterly={
            "FY2025Q4": complete_sheet(),
            "FY2026Q1": complete_sheet(),
            "FY2026Q2": complete_sheet(),
            # Q3 has no total equity: not complete
            "FY2026Q3": {**complete_sheet(), "total_equity": None},
        },
    )
    assert opening_period(history).key == "FY2026Q2"
    assert forecast_years(history, 5) == [2026, 2027, 2028, 2029, 2030]  # opening Q2


def test_a_quarter_without_revenue_is_not_an_opening() -> None:
    history = make_history(
        {2025: {"revenue": 400}},
        quarterly={"FY2026Q1": complete_sheet(), "FY2026Q2": {**complete_sheet(), "revenue": None}},
    )
    assert opening_period(history).key == "FY2026Q1"


@pytest.mark.parametrize(
    "missing", ["total_assets", "total_liabilities_and_equity", "total_equity", "revenue"]
)
def test_each_total_is_needed(missing: str) -> None:
    history = make_history({2025: {**complete_sheet(), missing: None}})
    with pytest.raises(ForecastUnavailable, match="No complete balance sheet to start from"):
        opening_period(history)


def test_an_opening_q4_starts_the_next_year() -> None:
    history = make_history({2025: {"revenue": 400}}, quarterly={"FY2025Q4": complete_sheet()})
    assert opening_period(history).key == "FY2025Q4"
    assert forecast_years(history, 10) == list(range(2026, 2036))


def test_an_annual_only_company_opens_on_its_latest_complete_year() -> None:
    history = make_history({2024: complete_sheet(), 2025: complete_sheet(), 2026: {"revenue": 5}})
    opening = opening_period(history)
    assert (opening.key, opening.fiscal_period) == ("FY2025", "FY")
    assert forecast_years(history, 5) == [2026, 2027, 2028, 2029, 2030]


def test_no_statements_is_unavailable() -> None:
    with pytest.raises(ForecastUnavailable, match="No complete balance sheet"):
        opening_period(make_history({}))


# --- quarterly history (docs/erd/forecasting.md "Quarterly drivers" -> History) -----------------

# Q2 FY2025 (2025-04-01..2025-06-30, 91 days) with every driver input; its year-ago quarter and the
# quarter before it (Q1 FY2025) give the prior values.
Q2_2025 = {
    "revenue": 50,
    "gross_profit": 20,
    "cost_of_revenue": 30,
    "rnd": 5,
    "sga": 10,
    "other_operating_expenses": -1,
    "d_and_a": "2.5",
    "sbc": "1.5",
    "other_nonoperating_income": "0.5",
    "interest_expense": 3,
    "total_debt": 140,
    "pretax_income": 25,
    "income_tax": "5.25",
    "net_income": 20,
    "net_income_nci": 1,
    "net_income_common": 19,
    "receivables": 10,
    "inventory": 12,
    "accounts_payable": 6,
    "capex": -4,
    "debt_issued": 10,
    "debt_repaid": -5,
    "buybacks": -8,
    "dividends_paid": "-3.8",
    "shares_diluted": 98,
}
Q2_2024 = {"revenue": 40, "shares_diluted": 100}
Q1_2025 = {"revenue": 45, "total_debt": 100}


def quarterly_history(**extra: Mapping[str, Any]) -> ForecastHistory:
    quarters: dict[str, Mapping[str, Any]] = {
        "FY2024Q2": Q2_2024,
        "FY2025Q1": Q1_2025,
        "FY2025Q2": Q2_2025,
    }
    return make_history(
        {2024: {"revenue": 1}, 2025: {"revenue": 1}}, quarterly={**quarters, **extra}
    )


def test_every_quarterly_history_formula_on_one_quarter() -> None:
    history = quarterly_history(FY2025Q2={**Q2_2025, **complete_sheet(50)})
    got = historical_quarter_drivers(history, GROWTH)
    quarter = {code: v for (code, key), v in got.items() if key == "FY2025Q2"}
    interest = quarter.pop("interest_rate")
    assert interest is not None
    # 3 / mean(100, 140) annualised over the quarter's 91 days
    assert abs(interest - D(3) / D(120) * D(365) / D(91)) < D("1e-15")
    assert quarter == {
        "revenue_growth": D("0.25"),  # 50 / 40 - 1, the same quarter a year earlier
        "gross_margin": D("0.4"),
        "rnd_pct_revenue": D("0.1"),
        "sga_pct_revenue": D("0.2"),
        "other_opex_pct_revenue": D("-0.02"),
        "d_and_a_pct_revenue": D("0.05"),
        "sbc_pct_revenue": D("0.03"),
        "other_nonoperating_pct_revenue": D("0.01"),
        "tax_rate": D("0.21"),  # 5.25 / 25
        "nci_share": D("0.05"),  # 1 / 20
        "receivable_days": D("18.2"),  # 10 / 50 × 91
        "inventory_days": D("36.4"),  # 12 / 30 × 91
        "payable_days": D("18.2"),  # 6 / 30 × 91
        "capex_pct_revenue": D("0.08"),
        "debt_issued": D("10"),  # the quarter's amount
        "debt_repaid": D("5"),
        "min_cash": None,
        "buybacks": D("8"),
        "dividend_payout": D("0.2"),  # 3.8 / 19
        "share_change": D("-0.02"),  # 98 / 100 - 1
    }


def test_the_history_is_the_last_eight_actual_quarters() -> None:
    quarters = {
        f"FY{y}Q{q}": {"revenue": 10 + i}
        for i, (y, q) in enumerate((y, q) for y in (2023, 2024, 2025) for q in (1, 2, 3, 4))
    }
    quarters["FY2025Q4"] = {**quarters["FY2025Q4"], **complete_sheet(21)}
    history = make_history({2025: {"revenue": 1}}, quarterly=quarters)
    shown = history_quarters(history)
    assert [p.key for p in shown] == [f"FY{y}Q{q}" for y in (2024, 2025) for q in (1, 2, 3, 4)]
    assert {key for (_, key) in historical_quarter_drivers(history, GROWTH)} == {
        p.key for p in shown
    }
    # Q4 is a period like any other; its year-ago quarter is Q4 of the year before.
    got = historical_quarter_drivers(history, GROWTH)
    assert got[("revenue_growth", "FY2025Q4")] == D(21) / D(17) - 1


def test_quarters_after_the_opening_are_not_history() -> None:
    quarters = {
        "FY2025Q1": {"revenue": 10, **complete_sheet(10)},
        "FY2025Q2": {"revenue": 11},  # no balance sheet: not an opening candidate
    }
    history = make_history({2025: {"revenue": 1}}, quarterly=quarters)
    assert [p.key for p in history_quarters(history)] == ["FY2025Q1"]


def test_a_missing_year_ago_quarter_or_previous_quarter_gives_null() -> None:
    history = quarterly_history(FY2025Q2={**Q2_2025, **complete_sheet(50)})
    got = historical_quarter_drivers(history, GROWTH)
    assert got[("revenue_growth", "FY2025Q1")] is None  # no Q1 FY2024
    assert got[("interest_rate", "FY2025Q1")] is None  # no quarter before Q1 FY2025
    assert got[("share_change", "FY2025Q1")] is None
    # the rule needs total_debt in both quarters
    without = make_history(
        {2024: {"revenue": 1}, 2025: {"revenue": 1}},
        quarterly={"FY2025Q1": {"revenue": 45}, "FY2025Q2": {**Q2_2025, **complete_sheet(50)}},
    )
    assert historical_quarter_drivers(without, GROWTH)[("interest_rate", "FY2025Q2")] is None


def test_quarterly_days_use_the_length_of_the_quarter() -> None:
    # a 14-week quarter: 2024-07-01..2024-10-05 is 97 days
    history = make_history(
        {2024: {"revenue": 1}},
        quarterly={"FY2024Q4": {**Q2_2025, **complete_sheet(50)}},
        dates={"FY2024Q4": (date(2024, 7, 1), date(2024, 10, 5))},
    )
    got = historical_quarter_drivers(history, GROWTH)
    assert got[("receivable_days", "FY2024Q4")] == D("19.4")  # 10 / 50 × 97


def test_segment_and_kpi_growth_read_the_quarterly_series() -> None:
    cloud = SeriesHistory(
        7, "business", "Cloud", "revenue", "USD", {}, {(2024, "Q2"): D(100), (2025, "Q2"): D(130)}
    )
    history = quarterly_history(FY2025Q2={**Q2_2025, **complete_sheet(50)})
    history = replace(history, segment_series=(cloud,))
    settings = ScenarioSettings("segments", "business")
    got = historical_quarter_drivers(history, settings)
    assert got[("segment_growth:7", "FY2025Q2")] == D("0.3")
    assert ("revenue_growth", "FY2025Q2") not in got  # not a driver of the segments method


def test_an_annual_only_company_has_no_quarterly_history() -> None:
    history = make_history({2025: {"revenue": 1}})
    assert history_quarters(history) == []
    assert historical_quarter_drivers(history, GROWTH) == {}


def test_a_missing_quarter_between_two_gives_no_interest_rate() -> None:
    # Q2 FY2025 is absent: the mean debt of Q1 and Q3 spans two quarters, so no rate (annualising
    # it by Q3's days alone would double it).
    history = make_history(
        {2024: {"revenue": 1}, 2025: {"revenue": 1}},
        quarterly={
            "FY2025Q1": {"revenue": 45, "total_debt": 100},
            "FY2025Q3": {**Q2_2025, **complete_sheet(50)},
        },
    )
    got = historical_quarter_drivers(history, GROWTH)
    assert got[("interest_rate", "FY2025Q3")] is None
