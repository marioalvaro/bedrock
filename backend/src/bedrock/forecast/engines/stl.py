"""Tier 3 STL: a quarterly series' trend, seasonal and residual, and its seasonal index
(docs/erd/forecasting.md "Statistical engines (M6)" → Engines). Not a `ForecastEngine`: it
decomposes, it does not forecast. Pure."""

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.interface import check_series

MIN_QUARTERS = 12
FLAT_RELATIVE = 1e-9  # a spread below this fraction of the series' size is round-off
INDEX_QUARTERS = 12  # the seasonal index averages this many last quarters
QUARTER_CODES = ("Q1", "Q2", "Q3", "Q4")


@dataclass(frozen=True)
class Decomposition:
    observed: list[float]
    trend: list[float]
    seasonal: list[float]
    residual: list[float]
    # max(0, 1 - var(residual) / var(seasonal + residual)); 0 when seasonal + residual has no
    # variance beyond float round-off (FLAT_RELATIVE of the series' size)
    strength: float


def decompose(values: pd.Series) -> Decomposition:
    """Robust STL with period 4 of a quarterly series (labelled by fiscal quarter). Raises
    EngineFailed with fewer than MIN_QUARTERS values, a non-finite value or a failed fit."""
    if len(values) < MIN_QUARTERS:
        raise EngineFailed(f"fewer than {MIN_QUARTERS} consecutive quarters")
    check_series("STL", values)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            fitted = STL(values, period=4, robust=True).fit()
        except Exception as exc:  # any statsmodels/numpy failure is a failed fit
            raise EngineFailed(f"STL could not fit: {exc}") from exc
    trend = np.asarray(fitted.trend, dtype=float)
    seasonal = np.asarray(fitted.seasonal, dtype=float)
    residual = np.asarray(fitted.resid, dtype=float)
    return Decomposition(
        observed=[float(v) for v in values],
        trend=trend.tolist(),
        seasonal=seasonal.tolist(),
        residual=residual.tolist(),
        strength=_strength(seasonal, residual, float(np.abs(values.to_numpy()).max())),
    )


def seasonal_index(values: pd.Series) -> dict[str, float]:
    """Q1..Q4: the mean seasonal component of each fiscal quarter over the last INDEX_QUARTERS
    quarters, minus the mean of the four (so they sum to 0). Raises EngineFailed as `decompose`."""
    seasonal = decompose(values).seasonal[-INDEX_QUARTERS:]
    quarters = [f"Q{p.quarter}" for p in values.index[-INDEX_QUARTERS:]]
    means = {
        q: float(np.mean([v for v, k in zip(seasonal, quarters, strict=True) if k == q]))
        for q in QUARTER_CODES
    }
    center = sum(means.values()) / len(means)
    return {q: means[q] - center for q in QUARTER_CODES}


def _strength(seasonal: np.ndarray, residual: np.ndarray, size: float) -> float:
    denominator = float(np.var(seasonal + residual))
    if denominator <= (FLAT_RELATIVE * size) ** 2:
        return 0.0
    return max(0.0, 1 - float(np.var(residual)) / denominator)
