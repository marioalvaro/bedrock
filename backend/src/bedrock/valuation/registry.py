"""The valuation methods (docs/erd/valuation.md "Interface" → Registry). Services call
`run_methods` and never name a method; a new method is one class and one entry here. Pure."""

from collections.abc import Sequence

from bedrock.valuation.dcf import DcfFcff
from bedrock.valuation.inputs import ResolvedInputs
from bedrock.valuation.interface import (
    MarketData,
    ValuationForecast,
    ValuationMethod,
    ValuationResult,
)
from bedrock.valuation.multiples import MultipleTargets

METHODS: tuple[ValuationMethod, ...] = (DcfFcff(), MultipleTargets())


def run_methods(
    forecast: ValuationForecast,
    market: MarketData,
    inputs: ResolvedInputs,
    methods: Sequence[ValuationMethod] = METHODS,
) -> list[ValuationResult]:
    """Every method's results, in `methods` order."""
    return [result for method in methods for result in method.value(forecast, market, inputs)]
