"""Tier 2 ETS (docs/erd/forecasting.md "Statistical engines (M6)" → Engines). Pure."""

import math
import warnings
from collections.abc import Mapping
from typing import Any, ClassVar

from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.interface import ForecastResult, SeriesInput, check_series, result

# (meta trend, ETSModel keyword arguments), in tie-break order
CANDIDATES: tuple[tuple[str | None, Mapping[str, Any]], ...] = (
    (None, {}),
    ("damped", {"trend": "add", "damped_trend": True}),
)


class EtsEngine:
    code: ClassVar[str] = "ets"
    label: ClassVar[str] = "ETS"

    def forecast(
        self, data: SeriesInput, horizon: int, config: Mapping[str, Any]
    ) -> ForecastResult:
        """Additive-error ETS with no trend or a damped additive trend, the lowest AIC winning
        (ties: no trend); a candidate that raises or has a NaN
        AIC is skipped. Always fits the `pd.Series`
        (statsmodels 0.15.0 fails on `get_prediction` of a numpy fit). Raises EngineFailed."""
        values = data.values
        check_series(self.label, values)
        n = len(values)
        best: tuple[float, str | None, Any] | None = None
        error: Exception | None = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for trend, kwargs in CANDIDATES:
                try:
                    fitted = ETSModel(values, error="add", **kwargs).fit(disp=False)
                except Exception as exc:  # any statsmodels/numpy failure skips the candidate
                    error = exc
                    continue
                aic = float(fitted.aic)
                if math.isnan(aic):  # incomparable; -inf (a perfect fit) is a valid best
                    error = ValueError("the fit has no AIC")
                    continue
                if best is None or aic < best[0]:
                    best = (aic, trend, fitted)
            if best is None:
                raise EngineFailed(f"{self.label} could not fit: {error}")
            aic, trend, fitted = best
            try:
                prediction = fitted.get_prediction(start=n, end=n + horizon - 1)
                outer = prediction.summary_frame(alpha=0.10)
                inner = prediction.summary_frame(alpha=0.50)
            except Exception as exc:  # a forecast that raises is a failed fit
                raise EngineFailed(f"{self.label} could not fit: {exc}") from exc
        bands = {
            "p05": outer["pi_lower"].to_numpy(dtype=float),
            "p25": inner["pi_lower"].to_numpy(dtype=float),
            "p75": inner["pi_upper"].to_numpy(dtype=float),
            "p95": outer["pi_upper"].to_numpy(dtype=float),
        }
        point = outer["mean"].to_numpy(dtype=float)
        meta = {"engine": self.code, "trend": trend, "aic": aic}
        return result(self.label, values, point, bands, meta)
