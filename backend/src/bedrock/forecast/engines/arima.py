"""Tier 2 ARIMA (docs/erd/forecasting.md "Statistical engines (M6)" → Engines). Pure."""

import math
import warnings
from collections.abc import Mapping
from typing import Any, ClassVar

from statsmodels.tsa.arima.model import ARIMA

from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.interface import ForecastResult, SeriesInput, check_series, result

# (order, trend), in tie-break order
CANDIDATES: tuple[tuple[tuple[int, int, int], str], ...] = (
    ((0, 0, 0), "c"),
    ((1, 0, 0), "c"),
    ((0, 1, 1), "n"),
    ((1, 1, 0), "n"),
)


class ArimaEngine:
    code: ClassVar[str] = "arima"
    label: ClassVar[str] = "ARIMA"

    def forecast(
        self, data: SeriesInput, horizon: int, config: Mapping[str, Any]
    ) -> ForecastResult:
        """The candidate with the lowest AIC (ties: the first); a candidate that raises or has a NaN
        AIC is skipped. Raises EngineFailed when the series is too short or not finite,
        every candidate is skipped, or the forecast is not finite."""
        values = data.values
        check_series(self.label, values)
        best: tuple[float, tuple[int, int, int], str, Any] | None = None
        error: Exception | None = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for order, trend in CANDIDATES:
                try:
                    fitted = ARIMA(values, order=order, trend=trend).fit()
                except Exception as exc:  # any statsmodels/numpy failure skips the candidate
                    error = exc
                    continue
                aic = float(fitted.aic)
                if math.isnan(aic):  # incomparable; -inf (a perfect fit) is a valid best
                    error = ValueError("the fit has no AIC")
                    continue
                if best is None or aic < best[0]:
                    best = (aic, order, trend, fitted)
            if best is None:
                raise EngineFailed(f"{self.label} could not fit: {error}")
            aic, order, trend, fitted = best
            try:
                prediction = fitted.get_forecast(horizon)
                point = prediction.predicted_mean.to_numpy(dtype=float)
                outer = prediction.conf_int(alpha=0.10).to_numpy(dtype=float)
                inner = prediction.conf_int(alpha=0.50).to_numpy(dtype=float)
            except Exception as exc:  # a forecast that raises is a failed fit
                raise EngineFailed(f"{self.label} could not fit: {exc}") from exc
        bands = {"p05": outer[:, 0], "p25": inner[:, 0], "p75": inner[:, 1], "p95": outer[:, 1]}
        meta = {"engine": self.code, "order": list(order), "trend": trend, "aic": aic}
        return result(self.label, values, point, bands, meta)
