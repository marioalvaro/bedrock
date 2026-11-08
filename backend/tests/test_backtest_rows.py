"""The stored rows of a forecast (docs/erd/accountability.md "Stored rows"). Pure and synthetic."""

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from bedrock.backtest.snapshot import ValueRow, run_meta, value_rows
from bedrock.forecast.engine_defaults import Band, EngineRow
from bedrock.forecast.engines.driver import ForecastStatements, Opening
from bedrock.forecast.history import FLAT, ScenarioSettings
from bedrock.forecast.resolve import Resolved, ResolvedDrivers, Value
from bedrock.statements.periods import Period

D = Decimal


def period(key: str, fy: int, fp: str) -> Period:
    return Period(key, key, fy, fp, date(fy, 1, 1), date(fy, 12, 31))


Q1 = period("FY2026Q1", 2026, "Q1")
Q2 = period("FY2026Q2", 2026, "Q2")
FY26 = period("FY2026", 2026, "FY")
FY27 = period("FY2027", 2027, "FY")


def statements(
    values: Mapping[tuple[str, str], Decimal | None],
    periods: tuple[Period, ...] = (Q1, Q2, FY26, FY27),
) -> ForecastStatements:
    opening = Opening(period("FY2025", 2025, "FY"), {}, {})
    return ForecastStatements(periods, values, (), opening, frozenset())


def drivers(values: dict[tuple[str, int], Resolved], years: tuple[int, ...]) -> ResolvedDrivers:
    codes = tuple(dict.fromkeys(code for code, _ in values))
    return ResolvedDrivers(codes, years, values, (), frozenset())


NO_DRIVERS = drivers({}, ())
BAND = Band(D("0.01"), D("0.02"), D("0.04"), D("0.05"))


def engine(used: str | None, band: dict[int, Band] | None = None) -> EngineRow:
    return EngineRow("auto", used, None, band=band or {})  # type: ignore[arg-type]  # a test's used


def line(fy: int, fp: str, horizon: int, point: str, code: str = "revenue") -> ValueRow:
    return ValueRow("line", code, fy, fp, horizon, D(point), None, None, None, None, None, None)


def test_line_rows_come_years_first_with_horizons_counted_per_frequency() -> None:
    values = {
        ("revenue", "FY2026Q1"): D(10),
        ("revenue", "FY2026Q2"): D(11),
        ("revenue", "FY2026"): D(40),
        ("revenue", "FY2027"): D(44),
    }
    assert value_rows(statements(values), NO_DRIVERS, {}) == [
        line(2026, "FY", 1, "40"),
        line(2027, "FY", 2, "44"),
        line(2026, "Q1", 1, "10"),
        line(2026, "Q2", 2, "11"),
    ]


def test_a_null_line_value_has_no_row_but_keeps_its_horizon_slot() -> None:
    values = {("revenue", "FY2026"): None, ("revenue", "FY2027"): D(44)}
    assert value_rows(statements(values, (FY26, FY27)), NO_DRIVERS, {}) == [
        line(2027, "FY", 2, "44")
    ]


def test_a_company_with_no_quarterly_forecast_has_annual_rows_only() -> None:
    values = {("revenue", "FY2026"): D(40)}
    assert value_rows(statements(values, (FY26,)), NO_DRIVERS, {}) == [line(2026, "FY", 1, "40")]


def test_codes_limits_the_lines_and_never_the_drivers() -> None:
    values = {("revenue", "FY2026"): D(40), ("cash", "FY2026"): D(5)}
    driven = drivers({("tax_rate", 2026): Resolved(D("0.2"), "default")}, (2026,))
    rows = value_rows(statements(values, (FY26,)), driven, {}, codes=("cash",))
    assert [(r.kind, r.code) for r in rows] == [("line", "cash"), ("driver", "tax_rate")]


def test_a_driver_row_carries_its_source_and_year_horizon() -> None:
    driven = drivers(
        {
            ("tax_rate", 2026): Resolved(D("0.2"), "own"),
            ("tax_rate", 2027): Resolved(D("0.3"), "own"),
        },
        (2026, 2027),
    )
    assert value_rows(statements({}, ()), driven, {}) == [
        ValueRow(
            "driver", "tax_rate", 2026, "FY", 1, D("0.2"), None, None, None, None, None, "own"
        ),
        ValueRow(
            "driver", "tax_rate", 2027, "FY", 2, D("0.3"), None, None, None, None, None, "own"
        ),
    ]


def test_a_flat_or_missing_driver_has_no_row() -> None:
    values: dict[tuple[str, int], Resolved] = {
        ("goodwill", 2026): Resolved(FLAT, "default"),
        ("gross_margin", 2026): Resolved(None, None),
    }
    assert value_rows(statements({}, ()), drivers(values, (2026,)), {}) == []


def test_an_engine_driver_carries_the_band_with_p50_equal_to_the_point() -> None:
    driven = drivers({("tax_rate", 2026): Resolved(D("0.03"), "engine")}, (2026,))
    [row] = value_rows(statements({}, ()), driven, {"tax_rate": engine("ets", {2026: BAND})})
    assert (row.p05, row.p25, row.p50, row.p75, row.p95) == (
        D("0.01"),
        D("0.02"),
        D("0.03"),
        D("0.04"),
        D("0.05"),
    )


def quantiles(source: str, used: str | None) -> tuple[Decimal | None, ...]:
    value: Value = D("0.03")
    driven = drivers({("tax_rate", 2026): Resolved(value, source)}, (2026,))  # type: ignore[arg-type]  # each source
    [row] = value_rows(statements({}, ()), driven, {"tax_rate": engine(used, {2026: BAND})})
    return (row.p05, row.p25, row.p50, row.p75, row.p95)


NO_BAND = (None, None, None, None, None)


def test_an_own_value_has_no_band_even_when_the_engine_has_one() -> None:
    assert quantiles("own", "ets") == NO_BAND


def test_an_offset_has_no_band() -> None:
    assert quantiles("offset", "ets") == NO_BAND


def test_a_mean_has_no_band_even_with_source_engine() -> None:
    assert quantiles("engine", "mean") == NO_BAND


def test_an_engine_value_with_no_band_for_its_year_has_no_quantiles() -> None:
    driven = drivers({("tax_rate", 2027): Resolved(D("0.03"), "engine")}, (2027,))
    [row] = value_rows(statements({}, ()), driven, {"tax_rate": engine("ets", {2026: BAND})})
    assert row.p05 is None and row.p50 is None


def test_run_meta_round_trips_as_json_with_sorted_keys() -> None:
    settings = ScenarioSettings("volume_price", None, "units", "asp")
    text = run_meta(settings, {"tax_rate": EngineRow("mean", "mean", "a note")}, ["careful"])
    assert json.loads(text) == {
        "revenue_method": "volume_price",
        "segment_dimension": None,
        "volume_kpi": "units",
        "price_kpi": "asp",
        "engines": {"tax_rate": {"choice": "mean", "used": "mean", "note": "a note"}},
        "warnings": ["careful"],
    }
    keys = list(json.loads(text))
    assert keys == sorted(keys)
