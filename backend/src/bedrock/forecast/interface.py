"""The statistical engine interface (docs/erd/forecasting.md "Interfaces", "Statistical engines
(M6)" → Engines). Pure: statistics run in `float`; values cross back into drivers as `Decimal`.

Index rules: an annual series is on `pd.period_range(str(first_fy), periods=n, freq="Y")`, labelled
by fiscal year; a quarterly one on `freq="Q"` from `f"{first_fy}Q{n}"`, labelled by fiscal year and
quarter (never by calendar date). A forecast's `point` continues that index."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

import numpy as np
import pandas as pd

from bedrock.forecast.errors import EngineFailed

QUANTILES = ("p05", "p25", "p50", "p75", "p95")
MIN_VALUES = 4  # an engine refuses a shorter series rather than guess


@dataclass(frozen=True)
class SeriesInput:
    values: pd.Series  # float on a PeriodIndex (annual "Y" or quarterly "Q")
    exog: pd.DataFrame | None = None  # Tier 4 regressors (M8); always None in M6
    meta: Mapping[str, Any] = field(default_factory=dict)  # {"code": driver code, "unit": unit}


@dataclass(frozen=True)
class ForecastResult:
    point: pd.Series  # the future PeriodIndex
    quantiles: pd.DataFrame | None  # columns QUANTILES (p50 = point), indexed like `point`
    samples: np.ndarray | None  # Monte Carlo (M8); always None in M6
    meta: Mapping[str, Any]  # "engine", parameters, fit diagnostics


class ForecastEngine(Protocol):
    code: ClassVar[str]
    label: ClassVar[str]

    def forecast(
        self, data: SeriesInput, horizon: int, config: Mapping[str, Any]
    ) -> ForecastResult: ...


def annual_values(first_fy: int, values: Sequence[float]) -> pd.Series:
    """`values` on the annual index of fiscal years from `first_fy`."""
    index = pd.period_range(str(first_fy), periods=len(values), freq="Y")
    return pd.Series([float(v) for v in values], index=index, dtype=float)


def quarter_values(first_fy: int, first_quarter: int, values: Sequence[float]) -> pd.Series:
    """`values` on the quarterly index from quarter `first_quarter` of fiscal year `first_fy`."""
    index = pd.period_range(f"{first_fy}Q{first_quarter}", periods=len(values), freq="Q")
    return pd.Series([float(v) for v in values], index=index, dtype=float)


def future_index(values: pd.Series, horizon: int) -> pd.PeriodIndex:
    """The `horizon` periods after the last of `values`."""
    index = values.index
    if not isinstance(index, pd.PeriodIndex):
        raise TypeError("a series is indexed by periods")
    return pd.period_range(index[-1] + 1, periods=horizon, freq=index.freq)


def result(
    label: str,
    values: pd.Series,
    point: Sequence[float],
    bands: Mapping[str, Sequence[float]],
    meta: Mapping[str, Any],
) -> ForecastResult:
    """A `ForecastResult` on the future index of `values`, `bands` holding p05, p25, p75 and p95.
    Raises EngineFailed when any number is not finite."""
    index = future_index(values, len(point))
    columns = {"p05": bands["p05"], "p25": bands["p25"], "p50": point}
    columns |= {"p75": bands["p75"], "p95": bands["p95"]}
    frame = pd.DataFrame({k: np.asarray(v, dtype=float) for k, v in columns.items()}, index=index)
    if not np.isfinite(frame.to_numpy()).all():
        raise EngineFailed(f"{label} gave a non-finite forecast")
    return ForecastResult(frame["p50"].rename(None), frame, None, dict(meta))


def check_series(label: str, values: pd.Series) -> None:
    """Raises EngineFailed when the series is shorter than MIN_VALUES or a value is NaN or
    infinite."""
    if len(values) < MIN_VALUES:
        raise EngineFailed(f"{label} could not fit: {len(values)} values (needs {MIN_VALUES})")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise EngineFailed(f"{label} could not fit: the series is not finite")
