"""Tier 3 STL decomposition and the seasonal index (docs/erd/forecasting.md "Statistical engines
(M6)" → Engines). Real statsmodels, synthetic quarterly series."""

import math
import warnings
from collections.abc import Iterator

import numpy as np
import pytest

from bedrock.forecast.engines.stl import MIN_QUARTERS, decompose, seasonal_index
from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.interface import quarter_values

PATTERN = {"Q1": 3.0, "Q2": -1.0, "Q3": -1.0, "Q4": -1.0}


@pytest.fixture(autouse=True)
def no_warning_escapes() -> Iterator[None]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    assert [str(w.message) for w in caught] == []


def seasonal_series(
    n: int = 40, first_quarter: int = 1, seed: int = 3, noise: float = 0.02
) -> list[float]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        quarter = f"Q{(first_quarter - 1 + i) % 4 + 1}"
        out.append(100 + 0.5 * i + PATTERN[quarter] + rng.normal(0, noise))
    return out


@pytest.mark.parametrize("first_quarter", [1, 3])
def test_the_seasonal_index_recovers_a_noise_free_pattern_exactly(first_quarter: int) -> None:
    raw = seasonal_series(first_quarter=first_quarter, noise=0)

    index = seasonal_index(quarter_values(2015, first_quarter, raw))

    assert index == pytest.approx(PATTERN, abs=1e-6)


@pytest.mark.parametrize("first_quarter", [1, 3])
def test_the_seasonal_index_recovers_a_known_pattern(first_quarter: int) -> None:
    values = quarter_values(2015, first_quarter, seasonal_series(first_quarter=first_quarter))

    index = seasonal_index(values)

    assert list(index) == ["Q1", "Q2", "Q3", "Q4"]
    for quarter, expected in PATTERN.items():
        assert abs(index[quarter] - expected) < 0.05, (quarter, index[quarter])
    assert abs(sum(index.values())) < 1e-9


def test_a_strong_pattern_has_a_strength_near_one() -> None:
    out = decompose(quarter_values(2015, 1, seasonal_series()))

    assert out.strength > 0.9


def test_white_noise_has_a_low_strength() -> None:
    """One seed can land high (robust STL fits some pattern to any 4-periodic noise), so the
    property is on the median of 20 seeded series of 72 quarters, the fixtures' depth."""
    strengths = [
        decompose(
            quarter_values(2008, 1, list(np.random.default_rng(seed).normal(0, 1, 72)))
        ).strength
        for seed in range(20)
    ]

    assert all(0 <= s <= 1 for s in strengths)
    assert float(np.median(strengths)) < 0.3


def test_the_components_have_the_inputs_length_and_add_up() -> None:
    raw = seasonal_series(n=20)
    out = decompose(quarter_values(2015, 2, raw))

    for component in (out.observed, out.trend, out.seasonal, out.residual):
        assert len(component) == 20
        assert all(math.isfinite(v) for v in component)
    assert out.observed == pytest.approx(raw)
    for i in range(20):
        total = out.trend[i] + out.seasonal[i] + out.residual[i]
        assert total == pytest.approx(out.observed[i], abs=1e-9)


def test_the_index_is_the_mean_of_each_quarter_over_the_last_twelve_centered() -> None:
    """An older, larger pattern does not count: only the last 12 quarters' seasonal component."""
    old = [100 + (10.0 if i % 4 == 0 else 0.0) for i in range(30)]
    recent = [100 + PATTERN[f"Q{(30 + i) % 4 + 1}"] for i in range(12)]
    rng = np.random.default_rng(1)
    values = quarter_values(2010, 1, [v + rng.normal(0, 0.01) for v in old + recent])
    seasonal = decompose(values).seasonal[-12:]
    quarters = [f"Q{p.quarter}" for p in values.index[-12:]]
    means = {
        q: float(np.mean([v for v, k in zip(seasonal, quarters, strict=True) if k == q]))
        for q in PATTERN
    }
    center = sum(means.values()) / 4
    whole = zip(decompose(values).seasonal, values.index, strict=True)
    all_q1 = np.mean([v for v, k in whole if k.quarter == 1])

    index = seasonal_index(values)

    for quarter in PATTERN:
        assert index[quarter] == pytest.approx(means[quarter] - center, abs=1e-12)
    assert index["Q1"] < all_q1 - center  # the old +10 is out of the window


@pytest.mark.parametrize("n", [0, 1, MIN_QUARTERS - 1])
def test_fewer_than_twelve_quarters_fail(n: int) -> None:
    values = quarter_values(2015, 1, seasonal_series(n=n) if n else [])

    with pytest.raises(EngineFailed, match="^fewer than 12 consecutive quarters$"):
        decompose(values)
    with pytest.raises(EngineFailed, match="^fewer than 12 consecutive quarters$"):
        seasonal_index(values)


def test_twelve_quarters_are_enough() -> None:
    assert MIN_QUARTERS == 12
    out = decompose(quarter_values(2015, 1, seasonal_series(n=12)))

    assert len(out.trend) == 12


def test_a_non_finite_value_fails() -> None:
    raw = seasonal_series(n=16)
    raw[4] = math.nan

    with pytest.raises(EngineFailed, match="^STL could not fit: the series is not finite$"):
        decompose(quarter_values(2015, 1, raw))


def test_a_constant_has_zero_strength() -> None:
    out = decompose(quarter_values(2015, 1, [5.0] * 16))

    assert out.strength == 0
    assert seasonal_index(quarter_values(2015, 1, [5.0] * 16)) == pytest.approx(
        {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}, abs=1e-9
    )
