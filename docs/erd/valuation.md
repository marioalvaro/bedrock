# ERD · Valuation

> Split of [ERD.md](../ERD.md), originally §4 (`valuation_run` table), §6 (`ValuationMethod` interface) and §7 (valuation route).
> Product counterpart: [prd/valuation.md](../prd/valuation.md) (`FR-VAL`). The forecast → valuation → sensitivity / Monte Carlo flow diagram is in [erd/forecasting.md](forecasting.md#forecast--valuation-flow-m4m8-orig-52).
> Code: `backend/src/bedrock/valuation/` (`interface.py` · `registry.py` · `dcf.py` · `multiples.py` · `sensitivity.py`).

## Tables (orig. §4)
| Table | Key columns | Notes |
|---|---|---|
| `valuation_run` | id, forecast_run_id, method_code, inputs_json, value_per_share, equity_value, enterprise_value, details_json | M5 |

## Interface (orig. §6)
```python
# valuation/interface.py
class ValuationMethod(Protocol):
    code: ClassVar[str]                   # "dcf_fcff", "multiple_target"
    def value(self, forecast: Statements, market: MarketData, inputs: Mapping[str, Any]) -> ValuationResult: ...
```
Methods are added by registering in `valuation/registry.py` (plug-in convention: [ERD.md §12](../ERD.md#12-coding-conventions)).

## Sensitivity (orig. §5.2)
- Sensitivity: perturb a driver by ± Δ, re-run the forecast and valuation, and collect the results into a tornado chart or 2-D grid.
- Monte Carlo: sample drivers N times and produce percentile bands.

## API (orig. §7)
- `POST /forecast-runs/{id}/valuation`
