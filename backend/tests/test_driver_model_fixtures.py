"""The driver model on the recorded companies (AAPL, MSFT, COST, DE): Base defaults and Bull- and
Bear-like offsets, at the shortest and the longest horizon, pass every integrity check."""

import time
from decimal import Decimal
from functools import cache

import pytest

from bedrock.forecast.engines.driver import DriverModel, ForecastStatements, Horizon
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    default_drivers,
    forecast_years,
    opening_period,
)
from bedrock.forecast.resolve import DriverRow, resolve_drivers
from tests.forecast_data import fixture_history

GROWTH = ScenarioSettings("growth")
TICKERS = ["AAPL", "MSFT", "COST", "DE"]
# offsets on Base: (revenue growth, gross margin)
SCENARIOS = {"base": None, "bull": ("0.03", "0.01"), "bear": ("-0.03", "-0.01")}
HORIZONS = [Horizon(5, 4), Horizon(10, 8)]


@cache
def history(ticker: str) -> ForecastHistory:
    return fixture_history(ticker)


def forecast(ticker: str, scenario: str, horizon: Horizon) -> tuple[ForecastStatements, float]:
    h = history(ticker)
    years = forecast_years(h, horizon.years)
    # DE has no cost of revenue from FY2018, so its Base sets gross margin.
    base_rows = (
        [DriverRow("gross_margin", y, "value", Decimal("0.25")) for y in years]
        if ticker == "DE"
        else []
    )
    offsets = SCENARIOS[scenario]
    own_rows = (
        []
        if offsets is None
        else [
            DriverRow(code, y, "offset", Decimal(offset))
            for code, offset in zip(("revenue_growth", "gross_margin"), offsets, strict=True)
            for y in years
        ]
    )
    drivers = resolve_drivers(
        base_rows,
        own_rows if offsets else base_rows,
        default_drivers(h, GROWTH),
        years,
        is_base=offsets is None,
    )
    started = time.perf_counter()
    out = DriverModel().run(h, drivers, horizon, GROWTH)
    return out, time.perf_counter() - started


@pytest.mark.parametrize("horizon", HORIZONS, ids=lambda h: f"{h.years}y{h.quarters}q")
@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("ticker", TICKERS)
def test_every_integrity_check_passes(ticker: str, scenario: str, horizon: Horizon) -> None:
    out, seconds = forecast(ticker, scenario, horizon)
    assert out.integrity and all(c.ok for c in out.integrity), [
        c for c in out.integrity if not c.ok
    ]
    assert len(out.annual()) == horizon.years
    assert len(out.quarterly()) >= horizon.quarters
    assert seconds < 2  # NFR-02: a recompute


@pytest.mark.parametrize("ticker", TICKERS)
def test_years_after_the_quarter_span_grow_by_the_revenue_growth(ticker: str) -> None:
    out, _ = forecast(ticker, "bull", Horizon(10, 8))
    h = history(ticker)
    defaults = default_drivers(h, GROWTH)
    growth = defaults["revenue_growth"]
    assert isinstance(growth, Decimal)
    built = {q.fiscal_year for q in out.quarterly()}
    after = [p for p in out.annual() if p.fiscal_year not in built]
    assert after
    for year in after:
        previous = out.get("revenue", f"FY{year.fiscal_year - 1}")
        assert previous is not None
        assert out.get("revenue", year.key) == previous * (1 + growth + Decimal("0.03"))


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_forecast_starts_after_the_latest_fixture_quarter(ticker: str) -> None:
    h = history(ticker)
    latest = h.quarterly["BS"].periods[-1]
    assert opening_period(h) == latest
    out, _ = forecast(ticker, "base", Horizon(5, 4))
    first = out.quarterly()[0]
    number = int(latest.fiscal_period[1])
    assert (first.fiscal_year, first.fiscal_period) == (
        (latest.fiscal_year + 1, "Q1") if number == 4 else (latest.fiscal_year, f"Q{number + 1}")
    )
    assert out.annual()[0].fiscal_year == latest.fiscal_year + (number == 4)
    assert out.opening.period == latest
