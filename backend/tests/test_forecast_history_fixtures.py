"""Driver history and defaults of the recorded companies (AAPL, MSFT, COST, DE)."""

from decimal import Decimal

import pytest

from bedrock.forecast.drivers import DRIVERS, Follows
from bedrock.forecast.history import (
    ScenarioSettings,
    StatementValues,
    default_drivers,
    historical_drivers,
    historical_quarter_drivers,
    history_quarters,
    history_years,
)
from tests.forecast_data import fixture_history

GROWTH = ScenarioSettings("growth")
REQUIRED = [d.code for d in DRIVERS if d.fallback == "required" and "growth" in d.methods]


def missing_required(ticker: str) -> set[str]:
    defaults = default_drivers(fixture_history(ticker), GROWTH)
    return {code for code in REQUIRED if defaults[code] is None}


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST"])
def test_every_required_driver_has_a_default(ticker: str) -> None:
    assert REQUIRED == ["revenue_growth", "gross_margin", "tax_rate", "capex_pct_revenue"]
    assert missing_required(ticker) == set()


def test_deere_needs_only_gross_margin() -> None:
    # No cost of revenue from FY2018 (docs/erd/data.md "Known gaps after M2").
    assert missing_required("DE") == {"gross_margin"}


def test_microsoft_d_and_a_has_no_history_and_follows_capex() -> None:
    history = fixture_history("MSFT")
    got = historical_drivers(history, GROWTH)
    assert [got[("d_and_a_pct_revenue", fy)] for fy in history_years(history)] == [None] * 5
    assert default_drivers(history, GROWTH)["d_and_a_pct_revenue"] == Follows(
        "capex_pct_revenue", resolved=True
    )


def test_apple_fy2024_ratios_equal_the_10k() -> None:
    # Apple 10-K FY2024 (FYE 2024-09-28, accession 0000320193-24-000123), in USD millions:
    # total net sales 391,035; gross margin 180,683; income before provision for income taxes
    # 123,485; provision for income taxes 29,749; payments for acquisition of property, plant
    # and equipment 9,447.
    got = historical_drivers(fixture_history("AAPL"), GROWTH)
    assert got[("gross_margin", 2024)] == Decimal(180_683) / Decimal(391_035)
    assert got[("tax_rate", 2024)] == Decimal(29_749) / Decimal(123_485)
    assert got[("capex_pct_revenue", 2024)] == Decimal(9_447) / Decimal(391_035)


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST", "DE"])
def test_history_is_the_last_five_fiscal_years(ticker: str) -> None:
    history = fixture_history(ticker)
    years = history_years(history)
    assert len(years) == 5 and years == list(range(years[0], years[0] + 5))
    assert history.latest_fy_end is not None and history.latest_fy_end.year in (
        years[-1],
        years[-1] + 1,
    )


@pytest.mark.parametrize("ticker", ["AAPL", "COST"])
def test_quarterly_history_of_the_recorded_companies_follows_the_rules(ticker: str) -> None:
    history = fixture_history(ticker)
    quarters = history_quarters(history)
    assert len(quarters) == 8
    assert {p.fiscal_period for p in quarters} == {"Q1", "Q2", "Q3", "Q4"}  # derived Q4 included
    got = historical_quarter_drivers(history, GROWTH)
    cells = StatementValues(history.quarterly)
    for period in quarters:
        key = period.key
        year_ago = f"FY{period.fiscal_year - 1}{period.fiscal_period}"
        revenue, before = cells.get("revenue", key), cells.get("revenue", year_ago)
        assert revenue is not None and before is not None
        assert got[("revenue_growth", key)] == revenue / before - 1
        profit = cells.get("gross_profit", key)
        assert profit is not None
        assert got[("gross_margin", key)] == profit / revenue
        interest = got[("interest_rate", key)]
        assert interest is None or Decimal(0) <= interest < Decimal("0.2")  # an annual rate
    # nothing is read past the opening quarter
    assert {key for (_, key) in got} == {p.key for p in quarters}
