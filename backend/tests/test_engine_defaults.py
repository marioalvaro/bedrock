"""Engine defaults (docs/erd/forecasting.md "Statistical engines (M6)" → Defaults): Auto's holdout
selection, the explicit choices and their fallbacks, the run rule, clamping, the step mapping and
the inspection payload. A fake `fit` returns fixed points and records its calls; STL is real."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from bedrock.forecast.engine_defaults import (
    ENGINE_CODES,
    HOLDOUT,
    MIN_POINTS,
    Band,
    EngineCode,
    EngineDefaults,
    annual_series,
    driver_engines,
    engine_defaults,
    quarter_series,
)
from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.history import ForecastHistory, ScenarioSettings
from bedrock.forecast.interface import QUANTILES, ForecastResult, SeriesInput, future_index
from tests.forecast_data import complete_sheet, make_history

D = Decimal
GROWTH = ScenarioSettings("growth")
Value = Decimal | int | str | None
LAST_FY = 2025
YEARS = [2026, 2027, 2028, 2029, 2030]
CODE = "gross_margin"


def margins_history(
    margins: Sequence[str | None],
    quarterly: Mapping[str, Mapping[str, Decimal | int | str | None]] | None = None,
) -> ForecastHistory:
    """Revenue 100 in every year ending FY2025, gross profit = margin × 100 (None: no gross
    profit, so a null margin)."""
    first = LAST_FY - len(margins) + 1
    annual = {}
    for i, margin in enumerate(margins):
        fy = first + i
        values: dict[str, Decimal | int | str | None] = {"revenue": 100}
        values["gross_profit"] = None if margin is None else D(margin) * 100
        if fy == LAST_FY:
            values |= complete_sheet()
        annual[fy] = values
    return make_history(annual, quarterly)


def margins(n: int) -> list[str | None]:
    return [f"0.{40 + i % 5}" for i in range(n)]  # 0.40, 0.41, ... 0.44, 0.40, ...


Points = Sequence[float] | Exception


@dataclass
class FakeFit:
    """`holdout[code]` answers a fit on the run without its last HOLDOUT values, `full[code]` a fit
    on the whole run; each is a list of points (one per step, repeated as needed) or an exception
    to raise. A code missing from a table fails."""

    holdout: Mapping[str, Points] = field(default_factory=dict)
    full: Mapping[str, Points] = field(default_factory=dict)
    calls: list[tuple[str, str, int, str, int]] = field(default_factory=list)

    def __call__(self, code: str, data: SeriesInput, horizon: int) -> ForecastResult:
        last = data.values.index[-1]
        kind = "full" if last.year == LAST_FY else "holdout"
        self.calls.append((data.meta["code"], code, len(data.values), kind, horizon))
        answer = (self.full if kind == "full" else self.holdout).get(code)
        if answer is None:
            raise EngineFailed(f"{code} is not in the fake")
        if isinstance(answer, Exception):
            raise answer
        point = [answer[min(i, len(answer) - 1)] for i in range(horizon)]
        index = future_index(data.values, horizon)
        spread = {"p05": -0.1, "p25": -0.05, "p50": 0.0, "p75": 0.05, "p95": 0.1}
        quantiles = pd.DataFrame({q: np.asarray(point) + spread[q] for q in QUANTILES}, index=index)
        return ForecastResult(pd.Series(point, index=index), quantiles, None, {"engine": code})

    def calls_for(self, driver: str) -> list[tuple[str, int, str, int]]:
        return [c[1:] for c in self.calls if c[0] == driver]


def defaults_of(
    history: ForecastHistory,
    fit: Callable[[str, SeriesInput, int], ForecastResult],
    choices: Mapping[str, EngineCode] | None = None,
    years: Sequence[int] = YEARS,
) -> EngineDefaults:
    return engine_defaults(history, GROWTH, choices or {}, years, fit=fit)


# The last 3 of an 18-value run of margins(18) are 0.40, 0.41, 0.42 (i = 15, 16, 17).
ACTUAL_TAIL = [0.40, 0.41, 0.42]


def test_the_codes_and_constants_of_the_erd() -> None:
    assert ENGINE_CODES == ("auto", "mean", "arima", "ets", "blend", "stl")
    assert (MIN_POINTS, HOLDOUT) == (8, 3)


def test_auto_picks_the_lowest_holdout_error_and_refits_it_on_the_whole_run() -> None:
    fit = FakeFit(
        holdout={"arima": [0.50], "ets": ACTUAL_TAIL, "blend": [0.45]},
        full={"ets": [0.43, 0.44, 0.45, 0.46, 0.47]},
    )

    out = defaults_of(margins_history(margins(18)), fit)

    row = out.rows[CODE]
    assert (row.choice, row.used, row.note) == ("auto", "ets", None)
    assert [out.values[(CODE, y)] for y in YEARS] == [
        D("0.43"),
        D("0.44"),
        D("0.45"),
        D("0.46"),
        D("0.47"),
    ]
    assert fit.calls_for(CODE) == [
        ("arima", 15, "holdout", HOLDOUT),
        ("ets", 15, "holdout", HOLDOUT),
        ("blend", 15, "holdout", HOLDOUT),
        ("ets", 18, "full", 5),
    ]
    assert row.holdout["ets"] == D(0)
    assert row.holdout["arima"] == pytest.approx(D("0.09"), abs=D("1e-9"))
    assert set(row.holdout) == {"arima", "ets", "blend"}


@pytest.mark.parametrize(
    ("tied", "winner"),
    [
        (("arima", "ets", "blend"), "blend"),
        (("arima", "ets"), "ets"),
        (("arima",), "arima"),
    ],
)
def test_auto_breaks_ties_in_the_order_blend_ets_arima(tied: tuple[str, ...], winner: str) -> None:
    holdout: dict[str, Points] = {c: [0.60] for c in ("arima", "ets", "blend")}
    holdout |= {c: ACTUAL_TAIL for c in tied}
    fit = FakeFit(holdout=holdout, full={c: [0.3] for c in ("arima", "ets", "blend")})

    out = defaults_of(margins_history(margins(18)), fit)

    assert out.rows[CODE].used == winner


def test_auto_skips_a_failing_candidate() -> None:
    fit = FakeFit(
        holdout={"arima": EngineFailed("ARIMA could not fit: boom"), "ets": [0.6], "blend": [0.5]},
        full={"blend": [0.41]},
    )

    out = defaults_of(margins_history(margins(18)), fit)

    assert out.rows[CODE].used == "blend"
    assert set(out.rows[CODE].holdout) == {"ets", "blend"}


def test_auto_refits_the_next_best_when_the_winner_fails_on_the_whole_run() -> None:
    fit = FakeFit(
        holdout={"arima": [0.6], "ets": ACTUAL_TAIL, "blend": [0.5]},
        full={"ets": EngineFailed("ETS could not fit: boom"), "blend": [0.39]},
    )

    out = defaults_of(margins_history(margins(18)), fit)

    assert out.rows[CODE].used == "blend"
    assert out.values[(CODE, 2026)] == D("0.39")


def test_auto_with_no_engine_that_fits_keeps_the_mean() -> None:
    boom = EngineFailed("boom")
    fit = FakeFit(holdout={"arima": boom, "ets": boom, "blend": boom})

    out = defaults_of(margins_history(margins(18)), fit)

    row = out.rows[CODE]
    assert (row.used, row.note) == ("mean", "Auto: no engine could fit; 3-year mean")
    assert all((CODE, y) not in out.values for y in YEARS)
    assert row.band == {}


@pytest.mark.parametrize("n", [8, 9, 10])
def test_auto_with_eight_to_ten_years_takes_the_blend_without_a_holdout(n: int) -> None:
    fit = FakeFit(full={"blend": [0.44]})

    out = defaults_of(margins_history(margins(n)), fit)

    row = out.rows[CODE]
    assert row.used == "blend"
    assert row.note == f"Auto: {n} years of history, too few for a holdout; blend"
    assert fit.calls_for(CODE) == [("blend", n, "full", 5)]
    assert row.holdout == {}
    assert out.values[(CODE, 2030)] == D("0.44")


def test_auto_with_eleven_years_runs_the_holdout() -> None:
    fit = FakeFit(holdout={c: [0.4] for c in ("arima", "ets", "blend")}, full={"blend": [0.4]})

    defaults_of(margins_history(margins(11)), fit)

    assert [c[2] for c in fit.calls_for(CODE)] == ["holdout"] * 3 + ["full"]
    assert fit.calls_for(CODE)[0][1] == 8


@pytest.mark.parametrize("n", [1, 6, 7])
def test_auto_with_fewer_than_eight_years_keeps_the_mean(n: int) -> None:
    fit = FakeFit()

    out = defaults_of(margins_history(margins(n)), fit)

    row = out.rows[CODE]
    assert (row.used, row.note) == ("mean", f"Auto: {n} years of history (needs 8); 3-year mean")
    assert fit.calls_for(CODE) == []
    assert all((CODE, y) not in out.values for y in YEARS)


def test_a_null_in_the_middle_cuts_the_run_to_the_latest_consecutive_values() -> None:
    values = margins(18)
    values[8] = None  # FY2016: the run is FY2017..FY2025, 9 values
    fit = FakeFit(full={"blend": [0.4]})

    out = defaults_of(margins_history(values), fit)

    assert out.rows[CODE].note == "Auto: 9 years of history, too few for a holdout; blend"
    run = annual_series(margins_history(values), GROWTH, CODE)
    assert run is not None
    assert [p.year for p in run.values.index] == list(range(2017, 2026))
    assert run.meta == {"code": CODE, "unit": "pct"}
    assert run.values.dtype == float


def test_a_null_last_year_leaves_no_run() -> None:
    values = margins(17) + [None]
    fit = FakeFit()

    out = defaults_of(margins_history(values), fit)

    assert annual_series(margins_history(values), GROWTH, CODE) is None
    assert out.rows[CODE].note == "Auto: 0 years of history (needs 8); 3-year mean"
    assert fit.calls_for(CODE) == []


@pytest.mark.parametrize(
    ("choice", "label"), [("arima", "ARIMA"), ("ets", "ETS"), ("blend", "Blend")]
)
def test_an_explicit_engine_fits_once_on_the_whole_run(choice: EngineCode, label: str) -> None:
    fit = FakeFit(full={choice: [0.47]})

    out = defaults_of(margins_history(margins(18)), fit, {CODE: choice})

    row = out.rows[CODE]
    assert (row.choice, row.used, row.note) == (choice, choice, None)
    assert fit.calls_for(CODE) == [(choice, 18, "full", 5)]
    assert out.values[(CODE, 2028)] == D("0.47")
    assert row.band[2028] == Band(D("0.37"), D("0.42"), D("0.52"), D("0.57"))
    assert row.holdout == {}


@pytest.mark.parametrize(
    ("choice", "label"), [("arima", "ARIMA"), ("ets", "ETS"), ("blend", "Blend")]
)
def test_an_explicit_engine_on_a_short_run_keeps_the_mean(choice: EngineCode, label: str) -> None:
    fit = FakeFit(full={choice: [0.47]})

    out = defaults_of(margins_history(margins(6)), fit, {CODE: choice})

    row = out.rows[CODE]
    assert (row.used, row.note) == ("mean", f"{label}: 6 years of history (needs 8); 3-year mean")
    assert fit.calls_for(CODE) == []
    assert row.band == {}


def test_an_explicit_engine_that_fails_keeps_the_mean_with_its_message() -> None:
    fit = FakeFit(full={"arima": EngineFailed("ARIMA could not fit: boom")})

    out = defaults_of(margins_history(margins(18)), fit, {CODE: "arima"})

    row = out.rows[CODE]
    assert (row.used, row.note) == ("mean", "ARIMA could not fit: boom; 3-year mean")
    assert (CODE, 2026) not in out.values


def test_mean_sets_no_value_but_keeps_autos_band_for_the_cross_check() -> None:
    fit = FakeFit(
        holdout={"arima": [0.50], "ets": ACTUAL_TAIL, "blend": [0.45]},
        full={"ets": [0.43]},
    )

    out = defaults_of(margins_history(margins(18)), fit, {CODE: "mean"})

    row = out.rows[CODE]
    assert (row.choice, row.used, row.note) == ("mean", "mean", None)
    assert all((CODE, y) not in out.values for y in YEARS)
    assert row.band[2026] == Band(D("0.33"), D("0.38"), D("0.48"), D("0.53"))
    assert row.band_engine == "ets"
    assert set(row.holdout) == {"arima", "ets", "blend"}


def test_the_band_is_autos_winners_and_empty_when_auto_keeps_the_mean() -> None:
    fit = FakeFit(full={"blend": [0.44]})

    with_engine = defaults_of(margins_history(margins(9)), fit).rows[CODE]
    with_mean = defaults_of(margins_history(margins(5)), fit).rows[CODE]

    assert set(with_engine.band) == set(YEARS)
    assert with_engine.band[2030] == Band(D("0.34"), D("0.39"), D("0.49"), D("0.54"))
    assert with_mean.band == {}
    assert (with_engine.band_engine, with_mean.band_engine) == ("blend", None)


def test_an_explicit_engine_is_its_own_bands_engine() -> None:
    out = defaults_of(
        margins_history(margins(18)), FakeFit(full={"arima": [0.43]}), {CODE: "arima"}
    )

    assert out.rows[CODE].band_engine == "arima"


def quarters_with_pattern(n: int, pattern: Sequence[float]) -> dict[str, dict[str, Value]]:
    """n quarters ending at Q4 FY2025, revenue 100, gross margin 0.40 + the quarter's pattern."""
    out: dict[str, dict[str, Value]] = {}
    for i in range(n):
        index = 4 * LAST_FY + 3 - (n - 1 - i)
        fy, q = divmod(index, 4)
        out[f"FY{fy}Q{q + 1}"] = {"revenue": 100, "gross_profit": D(str(40 + pattern[q]))}
    return out


PATTERN = [3.0, -1.0, -1.0, -1.0]  # percentage points of margin


def test_stl_adds_the_seasonal_index_to_autos_values() -> None:
    history = margins_history(margins(9), quarters_with_pattern(16, PATTERN))
    fit = FakeFit(full={"blend": [0.44]})

    auto = defaults_of(history, fit)
    stl = defaults_of(history, fit, {CODE: "stl"})

    assert {k: v for k, v in stl.values.items() if k[0] == CODE} == {
        k: v for k, v in auto.values.items() if k[0] == CODE
    }
    row = stl.rows[CODE]
    assert (row.choice, row.used, row.seasonal) == ("stl", "blend", True)
    assert row.note == auto.rows[CODE].note
    index = stl.seasonal[CODE]
    assert list(index) == ["Q1", "Q2", "Q3", "Q4"]
    assert all(isinstance(v, Decimal) for v in index.values())
    assert [float(index[q]) for q in index] == pytest.approx([0.03, -0.01, -0.01, -0.01], abs=1e-6)
    assert abs(sum(index.values())) < D("1e-9")
    assert CODE not in auto.seasonal


def test_stl_with_fewer_than_twelve_quarters_has_no_pattern_and_says_so() -> None:
    history = margins_history(margins(18), quarters_with_pattern(11, PATTERN))
    fit = FakeFit(holdout={c: [0.4] for c in ("arima", "ets", "blend")}, full={"blend": [0.4]})

    out = defaults_of(history, fit, {CODE: "stl"})

    assert CODE not in out.seasonal
    assert out.rows[CODE].note == "STL: fewer than 12 consecutive quarters; no seasonal pattern"
    assert out.rows[CODE].used == "blend"


def test_stl_joins_its_note_to_autos() -> None:
    history = margins_history(margins(9))
    fit = FakeFit(full={"blend": [0.4]})

    out = defaults_of(history, fit, {CODE: "stl"})

    assert out.rows[CODE].note == (
        "Auto: 9 years of history, too few for a holdout; blend; "
        "STL: fewer than 12 consecutive quarters; no seasonal pattern"
    )


def test_stl_on_a_driver_that_is_not_seasonal_is_refused() -> None:
    with pytest.raises(ValueError, match="revenue_growth"):
        defaults_of(margins_history(margins(9)), FakeFit(), {"revenue_growth": "stl"})


def test_quarter_series_is_the_latest_consecutive_run_of_quarters() -> None:
    quarters = quarters_with_pattern(14, PATTERN)
    quarters["FY2023Q1"]["gross_profit"] = None  # cuts the run: FY2023Q2..FY2025Q4, 11 quarters
    history = margins_history(margins(9), quarters)

    run = quarter_series(history, GROWTH, CODE)

    assert run is not None
    assert len(run.values) == 11
    assert str(run.values.index[0]) == "2023Q2"
    assert str(run.values.index[-1]) == "2025Q4"


def test_flat_missing_and_following_defaults_run_no_engine() -> None:
    """No receivables (flat), no pretax income (tax rate required, none), no D&A (follows capex)."""
    fit = FakeFit(full={"blend": [0.4]})

    out = defaults_of(margins_history(margins(9)), fit)

    for code in ("receivable_days", "tax_rate", "d_and_a_pct_revenue"):
        row = out.rows[code]
        assert (row.used, row.note, row.band) == (None, None, {}), code
        assert fit.calls_for(code) == [], code
        assert all((code, y) not in out.values for y in YEARS), code
    assert out.rows["receivable_days"].seasonal is True
    assert out.rows["revenue_growth"].seasonal is False


def test_every_driver_of_the_method_has_a_row_in_catalog_order() -> None:
    out = defaults_of(margins_history(margins(9)), FakeFit(full={"blend": [0.4]}))

    assert list(out.rows)[:2] == ["revenue_growth", "gross_margin"]
    assert "segment_growth" not in "".join(out.rows)
    assert out.rows["gross_margin"].choice == "auto"


def test_a_value_outside_the_bounds_is_clamped_with_a_warning() -> None:
    fit = FakeFit(full={"ets": [1.5, 0.5]})

    out = defaults_of(margins_history(margins(18)), fit, {CODE: "ets"})

    assert out.values[(CODE, 2026)] == D(1)
    assert out.values[(CODE, 2027)] == D("0.5")
    assert "gross_margin FY2026: the ETS value is clamped to [-1, 1]" in out.warnings
    assert not any("FY2027" in w for w in out.warnings)


def test_values_keep_ten_decimals() -> None:
    fit = FakeFit(full={"arima": [0.123456789012345]})

    out = defaults_of(margins_history(margins(18)), fit, {CODE: "arima"})

    assert str(out.values[(CODE, 2026)]) == "0.1234567890"


@pytest.mark.parametrize(
    ("years", "horizon", "first_step"),
    [
        (YEARS, 5, 0),  # the first forecast year follows the last actual FY (a year in progress)
        ([2027, 2028, 2029, 2030, 2031], 6, 1),  # the annual table lags the quarters by a year
    ],
)
def test_a_forecast_year_takes_the_point_at_its_step(
    years: list[int], horizon: int, first_step: int
) -> None:
    steps = [0.30, 0.31, 0.32, 0.33, 0.34, 0.35]
    fit = FakeFit(full={"arima": steps})

    out = defaults_of(margins_history(margins(18)), fit, {CODE: "arima"}, years=years)

    assert fit.calls_for(CODE) == [("arima", 18, "full", horizon)]
    assert [out.values[(CODE, y)] for y in years] == [
        D(str(s)) for s in steps[first_step : first_step + 5]
    ]


def test_a_year_in_progress_with_a_quarterly_opening_is_step_one() -> None:
    quarters = {
        "FY2026Q1": {"revenue": 100, "gross_profit": 40},
        "FY2026Q2": {**complete_sheet(), "gross_profit": 40},
    }
    history = margins_history(margins(18), quarters)
    fit = FakeFit(full={"arima": [0.30, 0.31, 0.32, 0.33, 0.34]})

    out = defaults_of(history, fit, {CODE: "arima"})

    assert out.values[(CODE, 2026)] == D("0.3")
    assert out.values[(CODE, 2030)] == D("0.34")


# --- the inspection payload ---------------------------------------------------------------------


def test_driver_engines_fits_every_engine_on_the_whole_run_with_its_holdout() -> None:
    fit = FakeFit(
        holdout={"arima": [0.50], "ets": ACTUAL_TAIL, "blend": [0.45]},
        full={"arima": [0.46], "ets": [0.43], "blend": [0.44]},
    )
    history = margins_history(margins(18))

    out = driver_engines(history, GROWTH, CODE, "auto", YEARS, fit=fit)

    assert out.code == CODE
    assert [p for p, _ in out.run] == list(range(2008, 2026))
    assert out.run[-1][1] == D("0.42")
    assert [e.code for e in out.engines] == ["arima", "ets", "blend"]
    assert [e.label for e in out.engines] == ["ARIMA", "ETS", "Blend"]
    arima = out.engines[0]
    assert arima.values == {y: D("0.46") for y in YEARS}
    assert arima.band[2026] == Band(D("0.36"), D("0.41"), D("0.51"), D("0.56"))
    assert arima.holdout_mae == pytest.approx(D("0.09"), abs=D("1e-9"))
    assert arima.meta == {"engine": "arima"}
    assert arima.error is None
    assert out.engines[1].holdout_mae == D(0)
    assert (out.choice, out.used, out.note) == ("auto", "ets", None)
    assert out.mean == (D("0.40") + D("0.41") + D("0.42")) / 3
    assert out.seasonal is None  # no quarterly history


def test_driver_engines_reports_each_engines_error_on_a_short_run() -> None:
    out = driver_engines(margins_history(margins(6)), GROWTH, CODE, "auto", YEARS, fit=FakeFit())

    assert [e.error for e in out.engines] == [
        "ARIMA: 6 years of history (needs 8)",
        "ETS: 6 years of history (needs 8)",
        "Blend: 6 years of history (needs 8)",
    ]
    assert all(e.values == {} and e.band == {} and e.holdout_mae is None for e in out.engines)
    assert out.note == "Auto: 6 years of history (needs 8); 3-year mean"


def test_driver_engines_reports_a_failing_fit_and_no_holdout_under_eleven() -> None:
    fit = FakeFit(
        full={"arima": EngineFailed("ARIMA could not fit: boom"), "ets": [0.4], "blend": [0.4]}
    )

    out = driver_engines(margins_history(margins(9)), GROWTH, CODE, "arima", YEARS, fit=fit)

    assert out.engines[0].error == "ARIMA could not fit: boom"
    assert out.engines[1].error is None and out.engines[1].holdout_mae is None
    assert (out.used, out.note) == ("mean", "ARIMA could not fit: boom; 3-year mean")


def test_driver_engines_shows_the_seasonal_index_whatever_the_choice() -> None:
    history = margins_history(margins(9), quarters_with_pattern(16, PATTERN))

    out = driver_engines(history, GROWTH, CODE, "mean", YEARS, fit=FakeFit(full={"blend": [0.4]}))

    assert out.seasonal is not None
    assert float(out.seasonal["Q1"]) == pytest.approx(0.03, abs=1e-6)


def test_driver_engines_of_a_driver_with_no_numeric_default() -> None:
    out = driver_engines(
        margins_history(margins(9)), GROWTH, "tax_rate", "auto", YEARS, fit=FakeFit()
    )

    assert out.run == []
    assert out.mean is None and out.used is None
    assert all(e.error == "ETS: 0 years of history (needs 8)" for e in out.engines[1:2])
