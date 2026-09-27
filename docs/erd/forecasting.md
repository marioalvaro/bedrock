# ERD · Forecasting

> Split of [ERD.md](../ERD.md), originally §4 (scenario/driver/forecast tables), §5.2 (forecast & valuation flow), §6 (forecast interfaces, Tier 1 rules) and §7 (forecast routes).
> Product counterpart: [prd/forecasting.md](../prd/forecasting.md) (`FR-FCST`). Valuation that consumes forecasts: [erd/valuation.md](valuation.md). Macro series for Tier 4: [erd/data.md](data.md).
> Code: `backend/src/bedrock/forecast/` (`interface.py` · `registry.py` · `engines/{driver,arima,ets,stl,macro,montecarlo}.py`).

## Tables (orig. §4)
| Table | Key columns | Notes |
|---|---|---|
| `scenario` | id, company_id, name, is_default, created_at | M4 |
| `driver_value` | id, scenario_id, driver_code, fiscal_year, fiscal_period, value, source (manual/engine), engine_code NULL, distribution_json NULL | M4; distribution for Tier 5 |
| `driver_engine_choice` | scenario_id, driver_code, engine_code, config_json | M6; which engine produces a driver |
| `forecast_run` | id, scenario_id, created_at, as_of_date, config_hash, is_snapshot, engines_json | Snapshots immutable (M7, [erd/accountability.md](accountability.md)) |
| `forecast_value` | forecast_run_id, canonical_code, fiscal_year, fiscal_period, point, p05, p25, p50, p75, p95 | |

## Forecast & valuation flow, M4–M8 (orig. §5.2)
```
scenario drivers (manual) ─┐
engine defaults (T2/T3/T4)─┼─► resolved drivers per period ─► Tier 1 driver model
distributions (T5) ────────┘                                    │
                                     full 3-statement forecast (balanced)
                                                    │
                          valuation methods (DCF, multiples) ─► value/share
                                                    │
                     sensitivity: perturb driver ± Δ → re-run → tornado / 2-D grid
                     Monte Carlo: sample drivers N times → percentile bands
```

## Interfaces (orig. §6)
```python
# forecast/interface.py
@dataclass(frozen=True)
class SeriesInput:
    values: pd.Series            # PeriodIndex (annual 'Y' or quarterly 'Q'), float
    exog: pd.DataFrame | None    # Tier 4 macro regressors, aligned index
    meta: dict[str, Any]         # company, driver/canonical code, unit

@dataclass(frozen=True)
class ForecastResult:
    point: pd.Series                      # future PeriodIndex
    quantiles: pd.DataFrame | None        # columns p05,p25,p50,p75,p95
    samples: np.ndarray | None            # (n_samples, horizon) for Monte Carlo
    meta: dict[str, Any]                  # engine, params, fit diagnostics

class ForecastEngine(Protocol):
    code: ClassVar[str]                   # "arima", "ets", "stl", "macro_ols", ...
    def forecast(self, data: SeriesInput, horizon: int, config: Mapping[str, Any]) -> ForecastResult: ...
```
- Engines register themselves in `forecast/registry.py`. Selecting an engine per driver is data (`driver_engine_choice`), not code.
- **Tier 1 is not a `ForecastEngine`**. It is the `DriverModel` that consumes resolved drivers (from the manual inputs or from any engine) and derives the 3 statements:
  `DriverModel.run(history: Statements, drivers: DriverFrame, horizon) -> Statements`.
- Tier 1 integrity rules:
  - Balance sheet balances through a **cash plug** (a revolver draws if cash < minimum cash).
  - Retained earnings roll forward (RE₁ = RE₀ + NI − dividends − buyback-to-RE policy).
  - The cash-flow statement is derived from balance-sheet deltas plus the income statement.
  - Every run asserts these invariants, and the tests enforce them.
- Tier 5 wraps `DriverModel`: it samples drivers from their distributions, runs vectorized or looped, and aggregates the output quantiles.

## API (orig. §7)
- `CRUD /companies/{ticker}/scenarios`, `/scenarios/{id}/drivers`
- `POST /scenarios/{id}/forecast`
