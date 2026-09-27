# PRD · Valuation

> Split of [PRD.md](../PRD.md), originally §5.5 (Valuation).
> Engineering counterpart: [erd/valuation.md](../erd/valuation.md). Milestones and acceptance criteria: [PRD.md §8](../PRD.md#8-milestone-roadmap).
> Use cases served: UC-4, UC-5. Forecasts that feed valuation: [prd/forecasting.md](forecasting.md).

## Valuation — `VAL` (orig. §5.5)
| ID | Requirement | M |
|---|---|---|
| FR-VAL-01 | DCF on unlevered free cash flow (FCFF): WACC inputs (or a direct discount rate), terminal value by Gordon growth or exit multiple, EV → equity bridge, value per share. | M5 |
| FR-VAL-02 | Multiples-based target: a forecast metric (EPS, EBITDA, FCF, sales) × a chosen multiple (manual, own-history percentile, or peer median) → implied price. | M5 |
| FR-VAL-03 | Valuation per scenario, compared with the current price (upside/downside %). | M5 |
| FR-VAL-04 | Sensitivity: a 2-D table over any two inputs, and a tornado chart ranking drivers by their impact on value per share. | M5 |
| FR-VAL-05 | Valuation methods are pluggable. User-defined methods are a future milestone. | M5 / Future |
