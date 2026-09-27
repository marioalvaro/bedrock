# PRD · Data & Statements

> Split of [PRD.md](../PRD.md), originally §5.1 (Company & Data Layer) and §5.2 (Statements View).
> Engineering counterpart: [erd/data.md](../erd/data.md). Milestones and acceptance criteria: [PRD.md §8](../PRD.md#8-milestone-roadmap).
> Use cases served: UC-1, UC-3.

## Company & Data Layer — `DATA` (orig. §5.1)
| ID | Requirement | M |
|---|---|---|
| FR-DATA-01 | Add or remove followed companies by ticker (resolved to SEC CIK). | M1 |
| FR-DATA-02 | Ingest as-reported financial data from SEC EDGAR (XBRL company facts), annual and quarterly. | M1 |
| FR-DATA-03 | Map XBRL tags to a curated set of about 50–70 canonical line items, using default fallback tag lists and optional per-company overrides. | M1 |
| FR-DATA-04 | Show canonical items that could not be mapped or are missing for a company, so the user can fix them with an override. | M1 |
| FR-DATA-05 | Keep every filing vintage of a value (restatements). The default view uses the latest; history can be inspected per cell. | M1 |
| FR-DATA-06 | Derive Q4 figures for flow items (FY − Q1..Q3) and show that they are derived. | M1 |
| FR-DATA-07 | Daily price history and market cap from yfinance. | M1 |
| FR-DATA-08 | Refresh data manually, per company from the UI and via CLI. Show a last-refreshed timestamp. | M1 |
| FR-DATA-09 | Adjustment layer: add normalization adjustments (line item, period, amount, reason, category). Normalized = reported + adjustments. | M2 |
| FR-DATA-10 | Corporate actions: split-adjusted share counts and per-share figures. | M2 |
| FR-DATA-11 | Manual entry of segment/geographic breakdowns and KPIs (e.g., ARR, same-store sales, units). | M3 |
| FR-DATA-12 | Macro series from FRED (GDP, rates, CPI, unemployment, commodities, FX). | M8 |

## Statements View — `STMT` (orig. §5.2)
| ID | Requirement | M |
|---|---|---|
| FR-STMT-01 | Income statement, balance sheet and cash flow tables; periods as columns, line items as rows, first column pinned. | M1 |
| FR-STMT-02 | Toggles for annual/quarterly and TTM (TTM only for flow items). | M1 |
| FR-STMT-03 | Toggle between as-reported and normalized (from M2). Forecast periods appear visually distinct (from M4). | M1 |
| FR-STMT-04 | YoY growth and common-size (% of revenue / % of assets) sub-rows can be toggled. | M1 |
| FR-STMT-05 | Cell details: source tag, filing (form, accession, filed date), vintages and adjustments. | M1 |
| FR-STMT-06 | Export any table to CSV. | M1 |

For the table look, number formatting and provenance styling, see [prd/workspace.md](workspace.md#ux--design-orig-6).
