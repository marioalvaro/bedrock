"""Tier 2 engines on synthetic annual series (docs/erd/forecasting.md "Statistical engines (M6)" →
Engines): ARIMA, ETS, their blend and the registry. Real statsmodels, no fixtures."""

import math
import warnings
from collections.abc import Iterator

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.arima.model import ARIMA

from bedrock.forecast import registry
from bedrock.forecast.engines import arima, ets
from bedrock.forecast.engines.arima import ArimaEngine
from bedrock.forecast.engines.blend import BlendEngine
from bedrock.forecast.engines.ets import EtsEngine
from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.interface import (
    MIN_VALUES,
    QUANTILES,
    ForecastResult,
    SeriesInput,
    annual_values,
)

FIRST_FY = 2008
N = 18
H = 5


def series(values: list[float] | np.ndarray) -> SeriesInput:
    return SeriesInput(annual_values(FIRST_FY, list(values)), meta={"code": "x", "unit": "pct"})


def constant() -> SeriesInput:
    return series([0.4] * N)


def trend() -> SeriesInput:
    return series([0.1 + 0.01 * i for i in range(N)])


def ar1() -> SeriesInput:
    rng = np.random.default_rng(7)
    x = [0.3]
    for _ in range(N - 1):
        x.append(0.3 + 0.6 * (x[-1] - 0.3) + rng.normal(0, 0.02))
    return series(x)


def random_walk() -> SeriesInput:
    rng = np.random.default_rng(11)
    return series(0.2 + np.cumsum(rng.normal(0, 0.01, N)))


def noisy_level() -> SeriesInput:
    rng = np.random.default_rng(1)
    return series(0.4 + rng.normal(0, 0.01, N))


ENGINE_CODES = ["arima", "ets", "blend"]
SERIES = {
    "constant": constant,
    "trend": trend,
    "ar1": ar1,
    "random_walk": random_walk,
    "noisy_level": noisy_level,
}


@pytest.fixture(autouse=True)
def no_warning_escapes() -> Iterator[None]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    assert [str(w.message) for w in caught] == []


def run(code: str, data: SeriesInput, horizon: int = H) -> ForecastResult:
    return registry.fit(code, data, horizon)


@pytest.mark.parametrize("code", ENGINE_CODES)
def test_a_constant_gives_a_flat_point_at_its_level(code: str) -> None:
    point = run(code, constant()).point.to_numpy()

    assert point.max() - point.min() < 1e-6
    assert abs(point.mean() - 0.4) < 1e-4


@pytest.mark.parametrize("code", ENGINE_CODES)
def test_a_linear_trend_gives_an_increasing_point(code: str) -> None:
    point = run(code, trend()).point.to_numpy()

    assert all(b > a for a, b in zip(point, point[1:], strict=False))
    assert point[0] > 0.1 + 0.01 * (N - 1)


@pytest.mark.parametrize("name", ["ar1", "random_walk"])
@pytest.mark.parametrize("code", ENGINE_CODES)
def test_noisy_series_give_finite_points(code: str, name: str) -> None:
    out = run(code, SERIES[name]())

    assert len(out.point) == H
    assert all(math.isfinite(v) for v in out.point)


@pytest.mark.parametrize("name", list(SERIES))
@pytest.mark.parametrize("code", ENGINE_CODES)
def test_quantiles_are_ordered_and_p50_is_the_point(code: str, name: str) -> None:
    out = run(code, SERIES[name]())

    assert out.quantiles is not None
    assert list(out.quantiles.columns) == list(QUANTILES)
    q = out.quantiles
    for column in QUANTILES:
        assert all(math.isfinite(v) for v in q[column]), column
    tol = 1e-12
    assert (q["p05"] <= q["p25"] + tol).all()
    assert (q["p25"] <= q["p50"] + tol).all()
    assert (q["p50"] <= q["p75"] + tol).all()
    assert (q["p75"] <= q["p95"] + tol).all()
    assert np.allclose(q["p50"].to_numpy(), out.point.to_numpy(), atol=1e-12)
    assert out.quantiles.index.equals(out.point.index)


@pytest.mark.parametrize("code", ENGINE_CODES)
def test_the_point_is_labelled_by_the_next_fiscal_years(code: str) -> None:
    out = run(code, ar1(), horizon=3)

    expected = pd.period_range(str(FIRST_FY + N), periods=3, freq="Y")
    assert out.point.index.equals(expected)
    assert [p.year for p in out.point.index] == [2026, 2027, 2028]


@pytest.mark.parametrize("code", ENGINE_CODES)
def test_samples_are_none_and_meta_names_the_engine(code: str) -> None:
    out = run(code, ar1())

    assert out.samples is None
    assert out.meta["engine"] == code


def test_arima_meta_names_the_order_and_trend_with_the_lowest_aic() -> None:
    meta = run("arima", ar1()).meta

    assert (tuple(meta["order"]), meta["trend"]) in arima.CANDIDATES
    assert math.isfinite(meta["aic"])


@pytest.mark.parametrize("name", list(SERIES))
def test_arima_keeps_the_candidate_with_the_lowest_aic(name: str) -> None:
    data = SERIES[name]()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aics = [
            float(ARIMA(data.values, order=order, trend=trend).fit().aic)
            for order, trend in arima.CANDIDATES
        ]
    best = arima.CANDIDATES[aics.index(min(aics))]

    meta = run("arima", data).meta

    assert (tuple(meta["order"]), meta["trend"]) == best
    assert meta["aic"] == pytest.approx(min(aics))


def test_ets_has_no_trend_on_a_noisy_level() -> None:
    assert run("ets", noisy_level()).meta["trend"] is None


def test_ets_takes_the_damped_trend_on_a_linear_trend() -> None:
    meta = run("ets", trend()).meta

    assert meta["trend"] == "damped"
    assert math.isfinite(meta["aic"])


@pytest.mark.parametrize("name", list(SERIES))
def test_the_blend_is_the_mean_of_arima_and_ets(name: str) -> None:
    data = SERIES[name]()
    a, e, b = run("arima", data), run("ets", data), run("blend", data)

    assert np.allclose(b.point, (a.point + e.point) / 2, atol=1e-9, rtol=0)
    assert a.quantiles is not None and e.quantiles is not None and b.quantiles is not None
    for column in QUANTILES:
        mean = (a.quantiles[column] + e.quantiles[column]) / 2
        assert np.allclose(b.quantiles[column], mean, atol=1e-9, rtol=0), column
    assert b.meta["parts"] == {"arima": a.meta, "ets": e.meta}


@pytest.mark.parametrize("code", ENGINE_CODES)
@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_a_non_finite_input_fails(code: str, bad: float) -> None:
    values = [0.1 + 0.01 * i for i in range(N)]
    values[5] = bad
    label = {"arima": "ARIMA", "ets": "ETS", "blend": "ARIMA"}[code]

    with pytest.raises(EngineFailed, match=f"^{label} could not fit: the series is not finite$"):
        run(code, series(values))


class _Boom:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise np.linalg.LinAlgError("boom")


def test_an_arima_fit_that_raises_fails_with_its_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arima, "ARIMA", _Boom)

    with pytest.raises(EngineFailed, match="^ARIMA could not fit: boom$") as raised:
        run("arima", ar1())
    assert raised.value.message == "ARIMA could not fit: boom"


def test_an_ets_fit_that_raises_fails_with_its_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ets, "ETSModel", _Boom)

    with pytest.raises(EngineFailed, match="^ETS could not fit: boom$"):
        run("ets", ar1())


def test_a_non_finite_forecast_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    real = ets.ETSModel

    class NanForecast:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.model = real(*args, **kwargs)

        def fit(self, **kwargs: object) -> object:
            result = self.model.fit(**kwargs)
            original = result.get_prediction

            def nan_prediction(**kw: object) -> object:
                prediction = original(**kw)
                frame = prediction.summary_frame
                prediction.summary_frame = lambda alpha: frame(alpha=alpha) * math.nan
                return prediction

            result.get_prediction = nan_prediction
            return result

    monkeypatch.setattr(ets, "ETSModel", NanForecast)

    with pytest.raises(EngineFailed, match="^ETS gave a non-finite forecast$"):
        run("ets", ar1())


@pytest.mark.parametrize("failing", ["arima", "ets"])
def test_the_blend_fails_with_the_failing_engines_message(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    module = arima if failing == "arima" else ets
    monkeypatch.setattr(module, "ARIMA" if failing == "arima" else "ETSModel", _Boom)
    label = "ARIMA" if failing == "arima" else "ETS"

    with pytest.raises(EngineFailed, match=f"^{label} could not fit: boom$"):
        run("blend", ar1())


@pytest.mark.parametrize("code", ENGINE_CODES)
def test_a_series_shorter_than_the_minimum_fails(code: str) -> None:
    label = {"arima": "ARIMA", "ets": "ETS", "blend": "ARIMA"}[code]
    short = [0.1, 0.2, 0.3][: MIN_VALUES - 1]

    with pytest.raises(EngineFailed, match=f"^{label} could not fit: 3 values \\(needs 4\\)$"):
        run(code, series(short))


@pytest.mark.parametrize("code", ENGINE_CODES)
def test_a_series_at_the_minimum_fits(code: str) -> None:
    assert len(run(code, series([0.1, 0.12, 0.11, 0.13][:MIN_VALUES])).point) == H


def test_the_registry_lists_the_engines_in_order() -> None:
    assert list(registry.ENGINES) == ["arima", "ets", "blend"]
    assert isinstance(registry.ENGINES["arima"], ArimaEngine)
    assert isinstance(registry.ENGINES["ets"], EtsEngine)
    assert isinstance(registry.ENGINES["blend"], BlendEngine)
    assert [e.code for e in registry.ENGINES.values()] == ["arima", "ets", "blend"]
    assert [e.label for e in registry.ENGINES.values()] == ["ARIMA", "ETS", "Blend"]


def test_an_unknown_engine_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        registry.fit("prophet", ar1(), 3)


def test_the_engines_are_deterministic() -> None:
    first, second = run("blend", ar1()), run("blend", ar1())

    assert first.point.equals(second.point)


def test_annual_values_are_labelled_by_fiscal_year() -> None:
    values = annual_values(2015, [1.0, 2.0, 3.0])

    assert values.index.equals(pd.period_range("2015", periods=3, freq="Y"))
    assert values.dtype == float


class _NanAic:
    """A fitted model whose AIC is NaN; everything else is the real fit's."""

    def __init__(self, fitted: object) -> None:
        self._fitted = fitted
        self.aic = math.nan

    def __getattr__(self, name: str) -> object:
        return getattr(self._fitted, name)


@pytest.mark.parametrize(
    ("module", "name", "label"), [(arima, "ARIMA", "arima"), (ets, "ETSModel", "ets")]
)
def test_a_candidate_with_a_nan_aic_is_skipped(
    monkeypatch: pytest.MonkeyPatch, module: object, name: str, label: str
) -> None:
    """The first candidate reports a NaN AIC; it must not shadow the others."""
    real = getattr(module, name)
    made: list[object] = []

    class FirstNan:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.model = real(*args, **kwargs)
            self.first = not made
            made.append(self)

        def fit(self, **kwargs: object) -> object:
            fitted = self.model.fit(**kwargs)
            return _NanAic(fitted) if self.first else fitted

    monkeypatch.setattr(module, name, FirstNan)

    meta = run(label, ar1()).meta

    assert not math.isnan(meta["aic"])
    assert len(made) > 1
