"""The Tier 2 engines, in order (docs/erd/forecasting.md "Statistical engines (M6)"). A new engine
is one class and one entry here. Pure."""

from collections.abc import Mapping

from bedrock.forecast.engines.arima import ArimaEngine
from bedrock.forecast.engines.blend import BlendEngine, Fit
from bedrock.forecast.engines.ets import EtsEngine
from bedrock.forecast.interface import ForecastEngine, ForecastResult, SeriesInput


def fit(code: str, data: SeriesInput, horizon: int) -> ForecastResult:
    """`horizon` steps of engine `code` on `data`. Raises KeyError for an unknown code and
    EngineFailed when the engine cannot forecast."""
    return ENGINES[code].forecast(data, horizon, {})


_ARIMA = ArimaEngine()
_ETS = EtsEngine()


def engines_with(parts_fit: Fit) -> Mapping[str, ForecastEngine]:
    """The engines, in order, with the blend reaching its parts through `parts_fit`: the service's
    memo passes itself, so a blend reuses the ARIMA and ETS fits already made."""
    return {"arima": _ARIMA, "ets": _ETS, "blend": BlendEngine(parts_fit)}


ENGINES: Mapping[str, ForecastEngine] = engines_with(fit)
