# PRD · Accountability (Backtesting & Audit)

> Split of [PRD.md](../PRD.md), originally §5.6 (Accountability).
> Engineering counterpart: [erd/accountability.md](../erd/accountability.md). Milestones and acceptance criteria: [PRD.md §8](../PRD.md#8-milestone-roadmap).
> Use cases served: UC-6.

## Accountability — `ACC` (orig. §5.6)
| ID | Requirement | M |
|---|---|---|
| FR-ACC-01 | Snapshot a forecast (scenario + engine outputs) with a timestamp. Snapshots are immutable. | M7 |
| FR-ACC-02 | Backtesting: as actuals land, compute errors (MAPE, bias, hit rate within range) by metric, by method and by horizon. | M7 |
| FR-ACC-03 | Historical backtests use only data available at the time (point-in-time vintages). | M7 |
| FR-ACC-04 | Assumption audit trail: every change to a driver, adjustment or override is logged with old/new value, time and an optional rationale. | M7 |
