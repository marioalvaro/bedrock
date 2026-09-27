# Stock Analysis & Forecasting Tool — Project Brainstorm

## 1. Vision
A personal, deep-dive fundamental analysis tool for a handful of companies I actively follow — similar to TradingView's "Fundamentals" tab (no charts), but with modular, extensible forecasting features layered on top of the raw data as the key differentiator.

## 2. Scope
- Deep-dive analysis for a small, hand-picked set of companies (not a broad market screener, at least for v1)
- Personal-use tool, accessible across devices (phone/tablet/laptop) via a web app

## 3. Core Feature Set

### 3.1 Fundamentals Data Layer
- Annual + quarterly data, both "as-reported" and "normalized" (adjusted for one-time items/restatements)
- Full 3-statement history (income statement, balance sheet, cash flow)
- Ratio library:
  - Profitability: margins, ROE, ROIC, ROA, DuPont breakdown
  - Liquidity: current ratio, quick ratio
  - Solvency: debt/EBITDA, interest coverage
  - Efficiency: asset turnover, DSO/DIO/DPO, cash conversion cycle
  - Per-share metrics
- Segment / geographic breakdown parsing
- Quality-of-earnings flags: accruals vs. cash flow divergence, rising DSO/inventory vs. revenue, goodwill/impairment risk, off-balance-sheet items
- Capital allocation tracking: buybacks, dividends, share count dilution/accretion, capex trend, M&A activity
- Relative valuation: comps sets, multiples (P/E, EV/EBITDA, P/S, P/FCF) vs. own historical range and peer range
- Guidance vs. actual tracking (log company guidance, compare to real outcomes over time)

### 3.2 Forecasting Engine (Modular)
**Key architectural decision:** not fully independent per-metric forecasting — that risks breaking 3-statement internal consistency (e.g., unrelated revenue/COGS forecasts implying a nonsensical margin trajectory). Instead, a layered/modular design:

1. **Tier 1 — Driver-based core**: a small set of manually tunable drivers (segment growth or volume×price revenue build, margin assumptions, capex-as-%-of-revenue, working capital ratios). Everything else in the 3 statements is derived algebraically from these, preserving accounting integrity.
2. **Tier 2 — Statistical time-series module**: ARIMA/ETS/Prophet-style forecasts. Used as (a) the default for any driver not manually customized, or (b) a cross-check/ensemble against the manual driver forecast.
3. **Tier 3 — Cyclicality/seasonality module**: decompose historical data into trend + seasonal + cyclical components. Standalone-useful for seasonal businesses; also feeds Tiers 1/2.
4. **Tier 4 — Macro-conditioned regression overlay** (optional, per sector/company): regress a metric against macro indicators (GDP growth, rates, commodity prices, FX) where relevant (e.g., a homebuilder vs. mortgage rates). Opt-in plug-in, not a default.
5. **Tier 5 — Monte Carlo / scenario blending**: combine driver assumptions with probability distributions for a forecast range rather than a single point estimate.

Each forecasting "engine" should share a common interface — `historical series + config → point forecast + range/distribution` — so methods are swappable/combinable per metric, and each method's accuracy can be backtested independently.

### 3.3 Self-Inputted Key Drivers
- Manual entry UI for driver assumptions (e.g., sales breakdown by segment, unit economics, KPIs like ARR/same-store sales)
- These drivers feed directly into the Tier 1 forecasting core

## 4. Quality-of-Life Features
- Scenario management: save bull/base/bear assumption sets per company, not just a single forecast
- Sensitivity/tornado analysis: which assumption moves the valuation output the most
- **Forecast accuracy backtesting**: log past forecasts, compare against actuals as they land, track error/hit rate by metric and by method over time — a key differentiator vs. TradingView
- Assumption audit trail: distinguish "as reported" vs. "normalized" vs. "forecasted" at a glance, with history of assumption changes and rationale
- Notes/thesis journal tied to specific line items or dates
- Multi-ticker comparison view (secondary to the deep-dive focus)
- Import/export (CSV/Excel) for driver assumptions
- Corporate action handling: stock splits, share count normalization, FX conversion for foreign filers

## 5. Tech Stack Decision
**Chosen direction: a web app, for true cross-device access (phone/tablet/laptop via browser).**

- **Backend**: Python (FastAPI) — houses data ingestion, the financial statement/ratio engine, and each forecasting module as clean, testable services
- **Database**: SQLite to start (file-based, zero-config, sufficient for a handful of companies plus assumptions/scenarios/notes/backtest logs); can migrate to Postgres later if ever needed
- **Frontend**: a real web frontend (React, or server-rendered pages + Plotly) for responsive, interactive views (scenario comparison, sensitivity tables, driver input forms) — beyond what a simple dashboard tool comfortably handles
- **Optional**: wrap as a PWA for an app-like icon/experience on mobile
- **Hosting**: self-hosted on own machine/home server/Raspberry Pi, accessed over the home network; Tailscale (or similar) for private remote access without public cloud hosting
- **Alternative MVP path**: prototype the data/forecast logic in Streamlit first (same backend logic, disposable UI), migrate to the full frontend once the engine is validated — reasonable if faster initial validation is preferred over polish

## 6. Data Sourcing Strategy
- **SEC EDGAR (Company Facts / XBRL API)** — primary source of truth for as-reported historical financial statement data (US filers, quarterly + annual), free. Note: XBRL tagging is inconsistent across companies/industries — needs a one-time normalization/mapping layer per company or industry template.
- **yfinance** — supplementary: quick price data, some ratios, fallback/cross-check against EDGAR
- **FRED (Federal Reserve Economic Data) API** — free; feeds the Tier 4 macro-indicator forecasting module (GDP, rates, CPI, unemployment, commodity prices, etc.)
- **Manual entry UI** — for data not reliably available via API: segment/KPI breakdowns, management guidance figures, own driver assumptions, quality-of-earnings notes, thesis journal

## 7. Decisions Made So Far
- Scope: deep-dive tool for a handful of companies (not a broad screener)
- Data sourcing: free sources (EDGAR + yfinance) + manual entry / light API (FRED for macro)
- Tech direction: web app (FastAPI + SQLite + web frontend) for cross-device robustness, with Streamlit as a possible faster MVP path

## 8. Open Questions / Next Technical Steps (for Claude Code planning)
- [ ] Design the database/data model (raw vs. normalized vs. forecasted figures, driver assumptions, scenarios, versioning, backtest logs)
- [ ] Sketch overall project structure & module breakdown
- [ ] Spec out the forecasting engine interface in detail (common input/output contract across Tiers 1–5)
- [ ] Design the EDGAR data ingestion + XBRL normalization pipeline
- [ ] Decide on final frontend approach (React vs. Streamlit-first MVP vs. server-rendered)
- [ ] Decide on initial company list to build/test against
