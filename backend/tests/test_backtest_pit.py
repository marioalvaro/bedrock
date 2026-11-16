"""Point-in-time origins and per-method runs (docs/erd/accountability.md "Backtest"). No database
and no statistics: the recorded history with a fake `fit` that records what it was asked."""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pytest

from bedrock.backtest.pit import BACKTEST_ORIGINS, MethodRun, origins, run_method
from bedrock.backtest.scoring import SCORED_CODES
from bedrock.forecast.drivers import SEASONAL
from bedrock.forecast.engine_defaults import ENGINE_CODES
from bedrock.forecast.history import ForecastHistory
from bedrock.forecast.interface import ForecastResult, SeriesInput, result
from tests.forecast_data import complete_sheet, fixture_history, make_history

ORIGIN = date(2019, 10, 31)  # AAPL's FY2019 10-K


@dataclass
class FakeFit:
    """Every engine repeats the series' last value, with a band of ±1%."""

    calls: list[str] = field(default_factory=list)

    def __call__(self, code: str, data: SeriesInput, horizon: int) -> ForecastResult:
        self.calls.append(code)
        last = float(data.values.iloc[-1])
        point = np.repeat(last, horizon)
        spread = abs(last) * 0.01
        bands = {
            "p05": (point - spread).tolist(),
            "p25": (point - spread / 2).tolist(),
            "p75": (point + spread / 2).tolist(),
            "p95": (point + spread).tolist(),
        }
        return result(code, data.values, point.tolist(), bands, {"engine": code})


def history() -> ForecastHistory:
    return fixture_history("AAPL", as_of=ORIGIN)


def days(n: int) -> list[date]:
    return [date(2010, 1, 1) + timedelta(days=i) for i in range(n)]


def test_origins_are_the_last_ten_before_the_newest_oldest_first() -> None:
    dates = days(13)
    assert origins(dates) == dates[2:12]
    assert len(origins(dates)) == BACKTEST_ORIGINS


def test_fewer_than_ten_dates_give_them_all_but_the_newest() -> None:
    dates = days(4)
    assert origins(dates) == dates[:3]


def test_one_date_has_no_actuals_after_it() -> None:
    assert origins(days(1)) == []


def test_no_dates_give_no_origins() -> None:
    assert origins([]) == []


def test_origins_sort_and_drop_duplicates() -> None:
    a, b, c = days(3)
    assert origins([c, a, b, a]) == [a, b]


@pytest.mark.parametrize("method", ENGINE_CODES)
def test_each_method_is_every_drivers_choice(method: str) -> None:
    run = run_method(history(), method, FakeFit())  # type: ignore[arg-type]  # an EngineCode
    assert run.error is None
    engines = json.loads(run.meta)["engines"]
    assert engines
    for code, row in engines.items():
        expected = "auto" if method == "stl" and code not in SEASONAL else method
        assert row["choice"] == expected, code


def test_a_method_uses_the_injected_fit() -> None:
    fit = FakeFit()
    run_method(history(), "arima", fit)
    assert "arima" in fit.calls


def test_no_manual_value_reaches_a_run() -> None:
    run = run_method(history(), "ets", FakeFit())
    sources = {r.source for r in run.rows if r.kind == "driver"}
    assert sources
    assert sources <= {"engine", "default"}


def test_the_run_is_on_the_growth_method() -> None:
    run = run_method(history(), "auto", FakeFit())
    assert json.loads(run.meta)["revenue_method"] == "growth"


def test_a_run_stores_the_scored_lines_and_the_drivers() -> None:
    run = run_method(history(), "auto", FakeFit())
    assert {r.code for r in run.rows if r.kind == "line"} == set(SCORED_CODES)
    assert any(r.kind == "driver" for r in run.rows)


def test_a_run_from_a_10k_starts_at_the_next_full_year() -> None:
    run = run_method(history(), "auto", FakeFit())
    first = min(r.fiscal_year for r in run.rows if r.kind == "line" and r.fiscal_period == "FY")
    assert first == 2020


def test_a_driver_nothing_sets_is_the_runs_error() -> None:
    thin = make_history({2024: {"revenue": 90}, 2025: complete_sheet()})
    run = run_method(thin, "auto", FakeFit())
    assert run.error is not None and run.error.startswith("Set these drivers:")
    assert run.rows == []
    assert isinstance(json.loads(run.meta)["engines"], dict)


def test_no_opening_is_the_runs_error() -> None:
    run = run_method(make_history({}), "auto", FakeFit())
    assert run == MethodRun([], run.meta, run.error)
    assert run.error is not None
    assert run.rows == []
