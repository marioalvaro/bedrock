# Bedrock — Product Requirements Document

> **What** Bedrock does and **why**. For *how* it is built, see [ERD.md](ERD.md). Original ideation: [brainstorm.md](brainstorm.md).
> This document is the product source of truth: when a product decision changes, update it here first.
> **Structure**: this file is the index and holds the cross-cutting sections (vision, users, NFRs, roadmap). Functional requirements and UX live in one file per area under [prd/](prd/) (§5–§6). Each split names the original section it came from.

## 1. Vision

A personal tool for deep fundamental analysis of a handful of hand-picked companies. It works like TradingView's "Fundamentals" tab (without price charting), plus a modular forecasting and valuation layer on top of the raw data. The differentiators are:

1. **Accounting-consistent forecasts.** A driver-based 3-statement model, with statistical engines layered on top.
2. **Forecast accountability.** Every forecast is snapshotted and later scored against actuals.
3. **Provenance.** Every number shows whether it is *as-reported*, *normalized* or *forecast*, and why.

## 2. Goals & Non-goals

### Goals
- Full annual and quarterly 3-statement history for followed companies, sourced for free from SEC EDGAR.
- A comprehensive ratio library, quality-of-earnings flags and capital-allocation tracking.
- Driver-based forecasts with bull/base/bear scenarios, feeding DCF and multiples valuations.
- Measuring forecast accuracy over time, by metric and by method.
- Use from phone, tablet and laptop through a browser.

### Non-goals
- A broad market screener or universe-wide data.
- Price or technical charting, and real-time quotes.
- Trading, brokerage integration or alerts.
- Multi-user accounts or sharing.
- Paid data vendors.
- Industry-specific statement schemas (banks, insurers, REITs) and foreign/IFRS filers in v1. These are future milestones (§8).

## 3. Target User

A single user: an individual investor who is strong in accounting and financial modeling and follows 5–20 companies closely. They want to build their own view of each business rather than consume someone else's. They use it:
- at a desk for deep work: building drivers, scenarios and notes;
- on a phone for quick look-ups: checking a ratio, reviewing a thesis note, seeing how last quarter compared to their forecast.

## 4. Primary Use Cases

| ID | As the user, I want to… | Area |
|---|---|---|
| UC-1 | add a ticker and see its full 3-statement history, annual and quarterly, within a minute | [data](prd/data.md), [workspace](prd/workspace.md) |
| UC-2 | inspect ratios and trends and spot quality-of-earnings red flags | [analysis](prd/analysis.md) |
| UC-3 | adjust reported figures for one-off items and see normalized figures, with the reason recorded | [data](prd/data.md) |
| UC-4 | build a driver-based forecast, save bull/base/bear scenarios and get a valuation for each | [forecasting](prd/forecasting.md), [valuation](prd/valuation.md) |
| UC-5 | see which assumptions move the valuation most (sensitivity/tornado) | [valuation](prd/valuation.md) |
| UC-6 | compare my past forecasts, and each method's forecasts, to actual results once they are reported | [accountability](prd/accountability.md) |
| UC-7 | log management guidance and track it against actual outcomes | [analysis](prd/analysis.md) |
| UC-8 | keep a thesis journal tied to companies, line items and dates | [workspace](prd/workspace.md) |
| UC-9 | compare a company against peers on multiples and ratios | [analysis](prd/analysis.md) |

## 5. Functional Requirements

Each requirement has an ID and a target milestone (see §8). IDs are stable; reference them in commits and checklists. The requirement tables live in the area files:

| Orig. § | Area | Prefix | File | Milestones |
|---|---|---|---|---|
| 5.1 | Company & Data Layer | `FR-DATA` | [prd/data.md](prd/data.md) | M1, M2, M3, M8 |
| 5.2 | Statements View | `FR-STMT` | [prd/data.md](prd/data.md) | M1 |
| 5.3 | Analysis | `FR-ANL` | [prd/analysis.md](prd/analysis.md) | M2, M3 |
| 5.4 | Forecasting | `FR-FCST` | [prd/forecasting.md](prd/forecasting.md) | M4, M6, M8 |
| 5.5 | Valuation | `FR-VAL` | [prd/valuation.md](prd/valuation.md) | M5 |
| 5.6 | Accountability | `FR-ACC` | [prd/accountability.md](prd/accountability.md) | M7 |
| 5.7 | Notes & Workspace | `FR-NOTE`, `FR-WS` | [prd/workspace.md](prd/workspace.md) | M1, M3, M9 |
| 5.8 | Access | `FR-AUTH` | [prd/auth.md](prd/auth.md) | M0 |

## 6. UX & Design

Design principles (§6.1), page map (§6.2), company page layout (§6.3) and charts (§6.4) are in [prd/workspace.md](prd/workspace.md#ux--design-orig-6).

## 7. Non-functional Requirements
| ID | Requirement |
|---|---|
| NFR-01 | Personal scale: ≤ 50 companies, and single-user concurrency is enough. |
| NFR-02 | Company page loads in < 1 s on the home network. A forecast recompute takes < 2 s (Monte Carlo < 10 s). |
| NFR-03 | As-reported data is never mutated. All user changes are additive (adjustments, overrides, audit log). |
| NFR-04 | Runs on a laptop via Docker Compose; the same setup is movable to a home server behind Tailscale. |
| NFR-05 | Uses free data sources only, and respects SEC fair-access rules (identifying User-Agent, ≤ 10 req/s). |
| NFR-06 | Backups: the database is a single file that is easy to back up. |

## 8. Milestone Roadmap

Each milestone must meet its acceptance criteria before the next starts.

| M | Name | Scope (requirement IDs) | Acceptance criteria |
|---|---|---|---|
| M0 | Scaffold | Monorepo, backend/frontend skeletons, Docker Compose, CI, FR-AUTH-01/02, empty shell UI with theme toggle | `docker compose up` serves a login page; after login, an empty company list; CI green |
| M1 | Data | FR-DATA-01..08, FR-STMT-01..06, FR-WS-01 | AAPL, MSFT, COST and DE show 3 statements (annual + quarterly, ≥ 10 years where available); balance sheets balance (within rounding) for all mapped periods; unmapped items listed |
| M2 | Analysis | FR-DATA-09/10, FR-ANL-01..06 | Ratios match golden values for the test companies; adjustments round-trip into normalized views; splits handled for AAPL |
| M3 | Context | FR-DATA-11, FR-ANL-07..09, FR-NOTE-01/02 | Peer comparison for a comps set; guidance log with hit/miss; notes linked to cells |
| M4 | Forecast core | FR-FCST-01..06 | Base/bull/bear scenarios produce balanced 3-statement forecasts; driver CSV/Excel round-trip |
| M5 | Valuation | FR-VAL-01..05 | DCF and multiples values per scenario; tornado and 2-D sensitivity |
| M6 | Statistical | FR-FCST-07/08/11 | ARIMA/ETS defaults for unset drivers; STL decomposition for COST quarterly revenue |
| M7 | Accountability | FR-ACC-01..04 | Snapshots scored against later actuals; point-in-time backtest over past periods; audit log |
| M8 | Advanced | FR-DATA-12, FR-FCST-09/10 | DE revenue macro regression; Monte Carlo fan chart and valuation distribution |
| M9 | Polish | FR-WS-02, PWA, home-server deploy | Installable on phone; reachable over Tailscale |
| Future | — | Industry templates (banks/insurers/REITs), foreign/IFRS filers + FX, user-defined valuation plug-ins, XBRL dimensional segment parsing, Prophet engine, scheduled refresh | — |

**Initial test companies**: AAPL, MSFT (clean filers), COST (seasonal retail, non-calendar fiscal year), DE (cyclical industrial, has a captive finance arm, which is a good test of how far the universal schema stretches).

## 9. Open Questions
- Exact canonical line-item list: to be finalized at M1 against the four test companies. ([data](prd/data.md))
- Default thresholds for the quality-of-earnings flags (M2). ([analysis](prd/analysis.md))
- How the ETS/ARIMA ensemble weights against manual drivers when both exist (M6). ([forecasting](prd/forecasting.md))
- How DE's financial-services segment is presented under the universal schema (M1/M2). ([data](prd/data.md))
