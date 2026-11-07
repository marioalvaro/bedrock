"""The Tier 2 engines, in order (docs/erd/forecasting.md "Statistical engines (M6)"). A new engine
is one class and one entry here. Pure."""

from collections.abc import Mapping

from bedrock.forecast.engines.arima import ArimaEngine
from bedrock.forecast.engines.blend import BlendEngine
from bedrock.forecast.engines.ets import EtsEngine
from bedrock.forecast.interface import ForecastEngine, ForecastResult, SeriesInput


def fit(code: str, data: SeriesInput, horizon: int) -> ForecastResult:
    """`horizon` steps of engine `code` on `data`. Raises KeyError for an unknown code and
    EngineFailed when the engine cannot forecast."""
    return ENGINES[code].forecast(data, horizon, {})


ENGINES: Mapping[str, ForecastEngine] = {
    "arima": ArimaEngine(),
    "ets": EtsEngine(),
    "blend": BlendEngine(fit),
}
