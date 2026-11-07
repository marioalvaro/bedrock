"""Tier 2 blend: the equal-weight mean of ARIMA and ETS (docs/erd/forecasting.md "Statistical
engines (M6)" → Engines). Pure."""

from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from bedrock.forecast.interface import QUANTILES, ForecastResult, SeriesInput

Fit = Callable[[str, SeriesInput, int], ForecastResult]
PARTS = ("arima", "ets")


class BlendEngine:
    """Reaches its parts through the registry's `fit` (injected), not by import."""

    code: ClassVar[str] = "blend"
    label: ClassVar[str] = "Blend"

    def __init__(self, fit: Fit) -> None:
        self._fit = fit

    def forecast(
        self, data: SeriesInput, horizon: int, config: Mapping[str, Any]
    ) -> ForecastResult:
        """½ ARIMA + ½ ETS for the point and each quantile column (an approximation of the
        blend's interval). Raises the first failing part's EngineFailed."""
        parts = [self._fit(code, data, horizon) for code in PARTS]
        point = (parts[0].point + parts[1].point) / 2
        frames = [p.quantiles for p in parts]
        if frames[0] is None or frames[1] is None:
            raise ValueError("a Tier 2 engine gave no quantiles")  # every part gives them
        columns = list(QUANTILES)
        quantiles = (frames[0][columns] + frames[1][columns]) / 2
        meta = {
            "engine": self.code,
            "parts": {c: p.meta for c, p in zip(PARTS, parts, strict=True)},
        }
        return ForecastResult(point, quantiles, None, meta)
