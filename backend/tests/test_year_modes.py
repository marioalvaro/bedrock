"""Year modes (FR-FCST-13; docs/erd/forecasting.md "Year modes"): the quarters a switch to "by
quarter" fills, and that the fill changes no forecast number on the recorded companies."""

from dataclasses import replace
from decimal import Decimal
from functools import cache

import pytest

from bedrock.forecast.drivers import QUARTERS
from bedrock.forecast.engines.driver import (
    FORECAST_HORIZON,
    DriverModel,
    ForecastStatements,
    forecast_quarters,
)
from bedrock.forecast.history import (
    FLAT,
    Default,
    ForecastHistory,
    ScenarioSettings,
    SeriesHistory,
    StatementValues,
    default_drivers,
    forecast_years,
)
from bedrock.forecast.modes import fill_quarters
from bedrock.forecast.resolve import DriverRow, ResolvedDrivers, resolve_drivers
from tests.forecast_data import fixture_history

D = Decimal
GROWTH = ScenarioSettings("growth")
YEARS = [2027, 2028]


def _resolve(
    base: list[DriverRow],
    own: list[DriverRow],
    is_base: bool,
    defaults: dict[str, Default] | None = None,
) -> ResolvedDrivers:
    defaults = defaults or {
        "revenue_growth": D("0.05"),
        "gross_margin": D("0.4"),
        "buybacks": D("400"),
        "tax_rate": FLAT,
        "interest_rate": None,
    }
    return resolve_drivers(base, own if not is_base else base, defaults, YEARS, is_base)


def _by_key(rows: list[DriverRow]) -> dict[tuple[str, str], DriverRow]:
    return {(r.code, r.fiscal_period): r for r in rows}


def test_base_gets_a_value_row_per_quarter_from_what_the_quarters_resolve_to() -> None:
    base = [
        DriverRow("gross_margin", 2027, "value", D("0.45")),
        DriverRow("buybacks", 2027, "value", D("800")),
    ]

    filled = _by_key(fill_quarters(2027, QUARTERS, _resolve(base, [], True), base, True))

    assert {k for k in filled if k[0] == "gross_margin"} == {
        ("gross_margin", q) for q in ("Q1", "Q2", "Q3", "Q4")
    }
    assert all(r.kind == "value" and r.fiscal_year == 2027 for r in filled.values())
    assert filled[("gross_margin", "Q2")].value == D("0.45")  # the year's own value
    assert filled[("revenue_growth", "Q3")].value == D("0.05")  # the default
    assert filled[("buybacks", "Q4")].value == D("200")  # a USD flow is a quarter amount


def test_base_gets_no_row_for_a_driver_that_is_flat_or_has_no_value() -> None:
    filled = fill_quarters(2027, QUARTERS, _resolve([], [], True), [], True)

    codes = {r.code for r in filled}
    assert "tax_rate" not in codes  # held flat
    assert "interest_rate" not in codes  # nothing sets it
    assert "gross_margin" in codes


def test_only_the_given_quarters_are_filled() -> None:
    """A year in progress has actual quarters, which are not forecast quarters."""
    filled = fill_quarters(2027, ("Q3", "Q4"), _resolve([], [], True), [], True)

    assert filled and {r.fiscal_period for r in filled} == {"Q3", "Q4"}


def test_only_the_asked_year_is_filled() -> None:
    filled = fill_quarters(2028, QUARTERS, _resolve([], [], True), [], True)

    assert filled and {r.fiscal_year for r in filled} == {2028}


def test_a_quarter_that_already_has_a_row_keeps_it() -> None:
    base = [DriverRow("gross_margin", 2027, "value", D("0.5"), "Q2")]

    filled = _by_key(fill_quarters(2027, QUARTERS, _resolve(base, [], True), base, True))

    assert ("gross_margin", "Q2") not in filled
    assert {("gross_margin", q) in filled for q in ("Q1", "Q3", "Q4")} == {True}


def test_bull_gets_rows_only_for_the_drivers_it_overrides_annually() -> None:
    base = [DriverRow("gross_margin", 2027, "value", D("0.45"))]
    own = [
        DriverRow("revenue_growth", 2027, "offset", D("0.03")),
        DriverRow("buybacks", 2027, "offset", D("40")),
        DriverRow("tax_rate", 2027, "offset", D("0.01")),  # Base holds it flat: ignored
    ]

    filled = _by_key(fill_quarters(2027, QUARTERS, _resolve(base, own, False), own, False))

    assert {code for code, _ in filled} == {"revenue_growth", "buybacks"}  # not gross_margin
    assert filled[("revenue_growth", "Q1")].kind == "offset"
    assert filled[("revenue_growth", "Q1")].value == D("0.03")
    assert filled[("buybacks", "Q3")].value == D("10")  # an annual USD offset is split in four


def test_bull_with_its_own_annual_value_gets_value_rows_for_the_quarters() -> None:
    own = [
        DriverRow("gross_margin", 2027, "value", D("0.5")),
        DriverRow("buybacks", 2027, "value", D("800")),
    ]

    filled = _by_key(fill_quarters(2027, QUARTERS, _resolve([], own, False), own, False))

    assert filled[("gross_margin", "Q4")].kind == "value"
    assert filled[("gross_margin", "Q4")].value == D("0.5")
    assert filled[("buybacks", "Q1")].value == D("200")


# -- the fill changes no forecast number ---------------------------------------------------------

TICKERS = ["AAPL", "MSFT", "COST", "DE"]
CASES = ["base", "bull", "bear"]


@cache
def _history(ticker: str) -> ForecastHistory:
    return fixture_history(ticker)


def _rows(ticker: str, case: str) -> tuple[list[DriverRow], list[DriverRow]]:
    """Base rows and the case's own rows: Base sets a value or two, Bull and Bear their default
    offsets and an offset or value of a USD flow, so the fill meets every row kind."""
    years = forecast_years(_history(ticker), FORECAST_HORIZON.years)
    base = [DriverRow("tax_rate", y, "value", D("0.2")) for y in years]
    base += [DriverRow("buybacks", y, "value", D("4000000000")) for y in years]
    if ticker == "DE":  # no cost of revenue since FY2018
        base += [DriverRow("gross_margin", y, "value", D("0.25")) for y in years]
    if case == "base":
        return base, base
    sign = 1 if case == "bull" else -1
    own = [DriverRow("revenue_growth", y, "offset", sign * D("0.03")) for y in years]
    own += [DriverRow("gross_margin", y, "offset", sign * D("0.01")) for y in years]
    own += [DriverRow("buybacks", y, "offset", sign * D("1000000000")) for y in years]
    own += [DriverRow("sga_pct_revenue", y, "value", D("0.07")) for y in years]
    return base, own


def _run(ticker: str, case: str, base: list[DriverRow], own: list[DriverRow]) -> ForecastStatements:
    h = _history(ticker)
    years = forecast_years(h, FORECAST_HORIZON.years)
    drivers = resolve_drivers(base, own, default_drivers(h, GROWTH), years, case == "base")
    return DriverModel().run(h, drivers, FORECAST_HORIZON, GROWTH)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("ticker", TICKERS)
def test_switching_every_span_year_to_quarterly_changes_no_forecast_number(
    ticker: str, case: str
) -> None:
    h = _history(ticker)
    years = forecast_years(h, FORECAST_HORIZON.years)
    span = forecast_quarters(h)
    span_years = sorted({y for y, _ in span})

    def quarters_of(year: int) -> list[str]:
        return [q for y, q in span if y == year]

    base, own = _rows(ticker, case)
    before = _run(ticker, case, base, own)

    base_resolved = resolve_drivers(base, base, default_drivers(h, GROWTH), years, True)
    own_resolved = resolve_drivers(base, own, default_drivers(h, GROWTH), years, case == "base")
    new_base, new_own = list(base), list(own)
    for year in span_years:
        new_base += fill_quarters(year, quarters_of(year), base_resolved, base, True)
        if case != "base":
            new_own += fill_quarters(year, quarters_of(year), own_resolved, own, False)
    if case == "base":
        new_own = new_base
    after = _run(ticker, case, new_base, new_own)

    assert len(new_own) > len(own)  # something was filled
    assert after.values.keys() == before.values.keys()
    changed = {
        k: (before.values[k], after.values[k])
        for k in before.values
        if before.values[k] != after.values[k]
    }
    assert not changed, list(changed.items())[:5]
    assert all(c.ok for c in after.integrity)


def _segments_history(ticker: str) -> ForecastHistory:
    """The recorded company with two business segments covering 80 % of its revenue in the last
    five fiscal years (no quarterly segment values: a switch must not need them)."""
    base = _history(ticker)
    revenue = {
        p.fiscal_year: v
        for p in base.annual["IS"].periods
        if (v := StatementValues(base.annual).get("revenue", p.key)) is not None
    }
    years = sorted(revenue)[-5:]
    series = tuple(
        SeriesHistory(
            i + 1,
            "business",
            f"S{i + 1}",
            "revenue",
            "USD",
            {y: revenue[y] * D(share) * (1 + D("0.01") * n * (i + 1)) for n, y in enumerate(years)},
        )
        for i, share in enumerate(("0.5", "0.3"))
    )
    return replace(base, segment_series=series)


@pytest.mark.parametrize("ticker", ["AAPL", "COST"])
def test_switching_a_segments_scenario_changes_no_forecast_number_after_the_stored_rounding(
    ticker: str,
) -> None:
    h = _segments_history(ticker)
    settings = ScenarioSettings("segments", segment_dimension="business")
    years = forecast_years(h, FORECAST_HORIZON.years)
    defaults = default_drivers(h, settings)
    resolved = resolve_drivers([], [], defaults, years, True)
    before = DriverModel().run(h, resolved, FORECAST_HORIZON, settings)
    span = forecast_quarters(h)

    rows: list[DriverRow] = []
    for year in sorted({y for y, _ in span}):
        quarters = [q for y, q in span if y == year]
        rows += [
            replace(r, value=r.value.quantize(D("1E-10")))  # what the database keeps
            for r in fill_quarters(year, quarters, resolved, [], True)
        ]
    after_drivers = resolve_drivers(rows, rows, defaults, years, True)
    after = DriverModel().run(h, after_drivers, FORECAST_HORIZON, settings)

    assert any(r.code.startswith("segment_growth:") for r in rows)
    keys = [k for k, v in before.values.items() if v is not None]
    assert [float(after.values[k] or 0) for k in keys] == pytest.approx(
        [float(before.values[k] or 0) for k in keys], rel=1e-8, abs=100
    )
