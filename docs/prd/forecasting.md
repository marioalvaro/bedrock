# PRD · Forecasting

> Split of [PRD.md](../PRD.md), originally §5.4 (Forecasting).
> Engineering counterpart: [erd/forecasting.md](../erd/forecasting.md). Milestones and acceptance criteria: [PRD.md §8](../PRD.md#8-milestone-roadmap).
> Use cases served: UC-4. Valuation built on forecasts: [prd/valuation.md](valuation.md).

## Forecasting — `FCST` (orig. §5.4)
| ID | Requirement | M |
|---|---|---|
| FR-FCST-01 | **Tier 1 driver model.** A small set of drivers (revenue build, either by segment or volume×price; margins; opex ratios; tax rate; capex % revenue; D&A; working-capital days; SBC; buybacks/dividends; debt schedule) produces a full, balanced 3-statement forecast. | M4 |
| FR-FCST-02 | Horizon: annual 5–10 years (configurable), plus quarterly for the next 4–8 quarters. | M4 |
| FR-FCST-03 | Driver input grid (spreadsheet-like), prefilled with historical values of each driver to anchor the assumptions. | M4 |
| FR-FCST-04 | Scenarios: named driver sets per company (bull/base/bear by default, user-extendable), with side-by-side comparison. | M4 |
| FR-FCST-05 | Import/export driver sets as CSV and Excel. | M4 |
| FR-FCST-06 | Integrity checks shown on each forecast: balance sheet balances, cash roll-forward, retained-earnings roll-forward. | M4 |
| FR-FCST-07 | **Tier 2 statistical engines** (ARIMA, ETS). Used as the default for drivers the user has not set manually, and as a cross-check against manual drivers. | M6 |
| FR-FCST-08 | **Tier 3 seasonality/cyclicality**: decompose a series into trend, seasonal and residual components; view it standalone; feeds quarterly forecasts. | M6 |
| FR-FCST-09 | **Tier 4 macro overlay** (opt-in per company/metric): regress a metric on selected FRED series and use it as a driver default. | M8 |
| FR-FCST-10 | **Tier 5 Monte Carlo**: attach distributions to drivers and produce forecast and valuation ranges (fan charts, percentiles). | M8 |
| FR-FCST-11 | For any driver, choose which engine produces it (manual, Tier 2, Tier 3, Tier 4, or a blend). | M6 |
