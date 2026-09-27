# ERD · Accountability (Backtesting & Audit)

> Split of [ERD.md](../ERD.md), originally §4 (`backtest_result`, `audit_log` tables), §5.3 (accountability flow) and §7 (snapshot/backtest routes).
> Product counterpart: [prd/accountability.md](../prd/accountability.md) (`FR-ACC`). The point-in-time read path `as_of(date)` is defined in [erd/data.md](data.md#read-paths-orig-4). Snapshotted runs are `forecast_run` rows ([erd/forecasting.md](forecasting.md)).
> Code: `backend/src/bedrock/backtest/` (`snapshot.py` · `scoring.py`).

## Tables (orig. §4)
| Table | Key columns | Notes |
|---|---|---|
| `backtest_result` | id, forecast_run_id, canonical_code, fiscal_year, fiscal_period, horizon, forecast, actual, abs_pct_error, in_range | M7 |
| `audit_log` | id, entity, entity_id, field, old_value, new_value, rationale, changed_at | M7 (write from M2 onward, where cheap) |

## Accountability flow, M7 (orig. §5.3)
```
snapshot(forecast_run) ──(time passes, refresh ingests actuals)──► score(snapshot, latest actuals)
point-in-time backtest: for past date d, build history via as_of(d), run engine, compare to actuals after d
```

## API (orig. §7)
- `POST /forecast-runs/{id}/snapshot`
- `GET /companies/{ticker}/backtest`
