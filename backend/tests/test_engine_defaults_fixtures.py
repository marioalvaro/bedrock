"""Engine defaults on the recorded companies (docs/erd/forecasting.md "Statistical engines (M6)" →
Tests): real statsmodels on AAPL, MSFT, COST and DE × Base, Bull and Bear, with every driver on
`auto` and with every seasonal driver on `stl`. The forecast runs and passes every integrity check,
and switching the span years to by-quarter changes no number."""

from decimal import Decimal
from functools import cache

import pytest

from bedrock.forecast.drivers import SEASONAL
from bedrock.forecast.engine_defaults import (
    HOLDOUT,
    MIN_POINTS,
    EngineCode,
    EngineDefaults,
    annual_series,
    engine_defaults,
)
from bedrock.forecast.engines.driver import (
    FORECAST_HORIZON,
    DriverModel,
    ForecastStatements,
    forecast_quarters,
)
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    default_drivers,
    forecast_years,
)
from bedrock.forecast.modes import fill_quarters
from bedrock.forecast.resolve import DriverRow, ResolvedDrivers, resolve_drivers
from tests.forecast_data import fixture_history

D = Decimal
GROWTH = ScenarioSettings("growth")
TICKERS = ["AAPL", "MSFT", "COST", "DE"]
CASES = {"base": None, "bull": ("0.03", "0.01"), "bear": ("-0.03", "-0.01")}
MODES = ["auto", "stl"]


@cache
def history(ticker: str) -> ForecastHistory:
    return fixture_history(ticker)


@cache
def engines(ticker: str, mode: str) -> EngineDefaults:
    h = history(ticker)
    choices: dict[str, EngineCode] = {c: "stl" for c in SEASONAL} if mode == "stl" else {}
    return engine_defaults(h, GROWTH, choices, forecast_years(h, FORECAST_HORIZON.years))


def rows(ticker: str, case: str) -> tuple[list[DriverRow], list[DriverRow]]:
    """Base rows (DE: gross margin set, it has no cost of revenue from FY2018) and the case's own
    rows (Bull and Bear: offsets on revenue growth and gross margin), as the M4 fixture test."""
    years = forecast_years(history(ticker), FORECAST_HORIZON.years)
    base = (
        [DriverRow("gross_margin", y, "value", D("0.25")) for y in years] if ticker == "DE" else []
    )
    offsets = CASES[case]
    if offsets is None:
        return base, base
    own = [
        DriverRow(code, y, "offset", D(offset))
        for code, offset in zip(("revenue_growth", "gross_margin"), offsets, strict=True)
        for y in years
    ]
    return base, own


def resolve(
    ticker: str,
    mode: str,
    case: str,
    base: list[DriverRow],
    own: list[DriverRow],
    quarterly_years: frozenset[int] = frozenset(),
) -> ResolvedDrivers:
    h = history(ticker)
    out = engines(ticker, mode)
    return resolve_drivers(
        base,
        own,
        default_drivers(h, GROWTH),
        forecast_years(h, FORECAST_HORIZON.years),
        case == "base",
        quarterly_years=quarterly_years,
        engine_values=out.values,
        seasonal=out.seasonal,
    )


def run(ticker: str, drivers: ResolvedDrivers) -> ForecastStatements:
    return DriverModel().run(history(ticker), drivers, FORECAST_HORIZON, GROWTH)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("ticker", TICKERS)
def test_the_forecast_on_engine_defaults_passes_every_integrity_check(
    ticker: str, case: str, mode: str
) -> None:
    base, own = rows(ticker, case)
    drivers = resolve(ticker, mode, case, base, own)

    assert drivers.missing_required() == []
    assert drivers.out_of_bounds() == []
    assert drivers.out_of_bounds_quarters() == []
    out = run(ticker, drivers)

    assert out.integrity and all(c.ok for c in out.integrity), [
        c for c in out.integrity if not c.ok
    ]
    built = [c for c in out.integrity if c.quarters_diff is not None]
    assert built  # a year built from its quarters: Q1..Q4 = FY checked
    sources = {r.source for r in drivers.values.values()}
    assert "engine" in sources
    if mode == "stl":
        assert "seasonal" in {r.source for r in drivers.quarter_values.values()}


def test_every_aapl_driver_with_eleven_years_runs_a_tier_2_engine() -> None:
    h = history("AAPL")
    out = engines("AAPL", "auto")
    defaults = default_drivers(h, GROWTH)

    long = [
        code
        for code, default in defaults.items()
        if isinstance(default, Decimal)
        and (run_ := annual_series(h, GROWTH, code)) is not None
        and len(run_.values) >= MIN_POINTS + HOLDOUT
    ]

    assert len(long) >= 10, long
    for code in long:
        assert out.rows[code].used in ("arima", "ets", "blend"), (code, out.rows[code])
        assert set(out.rows[code].holdout) == {"arima", "ets", "blend"}, code
        assert out.rows[code].band, code


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_seasonal_driver_on_stl_with_quarters_gets_an_index_summing_to_zero(
    ticker: str,
) -> None:
    out = engines(ticker, "stl")

    assert out.seasonal, ticker
    for code, index in out.seasonal.items():
        assert code in SEASONAL
        assert list(index) == ["Q1", "Q2", "Q3", "Q4"]
        assert abs(sum(index.values())) < D("1e-8"), code


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("ticker", TICKERS)
def test_switching_the_span_years_to_by_quarter_changes_no_number(
    ticker: str, case: str, mode: str
) -> None:
    h = history(ticker)
    span = forecast_quarters(h)
    span_years = sorted({y for y, _ in span})
    base, own = rows(ticker, case)
    before = run(ticker, resolve(ticker, mode, case, base, own))

    base_resolved = resolve(ticker, mode, "base", base, base)
    own_resolved = resolve(ticker, mode, case, base, own)
    new_base, new_own = list(base), list(own)
    for year in span_years:
        quarters = [q for y, q in span if y == year]
        new_base += fill_quarters(year, quarters, base_resolved, base, True)
        if case != "base":
            new_own += fill_quarters(year, quarters, own_resolved, own, False)
    if case == "base":
        new_own = new_base
    after = run(ticker, resolve(ticker, mode, case, new_base, new_own, frozenset(span_years)))

    assert len(new_base) > len(base)
    assert after.values.keys() == before.values.keys()
    changed = {k: (v, after.values[k]) for k, v in before.values.items() if after.values[k] != v}
    assert not changed, list(changed.items())[:5]
