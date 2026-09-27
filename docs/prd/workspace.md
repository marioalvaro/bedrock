# PRD · Workspace, Notes & UX

> Split of [PRD.md](../PRD.md), originally §5.7 (Notes & Workspace) and §6 (UX & Design).
> Engineering counterpart: [erd/workspace.md](../erd/workspace.md). Milestones and acceptance criteria: [PRD.md §8](../PRD.md#8-milestone-roadmap).
> Use cases served: UC-1 (company list), UC-8.

## Notes & Workspace — `NOTE`, `WS` (orig. §5.7)
| ID | Requirement | M |
|---|---|---|
| FR-NOTE-01 | Thesis journal per company. Markdown notes, optionally linked to a line item, period or date. | M3 |
| FR-NOTE-02 | A marker on linked cells opens the related notes. | M3 |
| FR-WS-01 | Company list (home) with key stats per company: price, market cap, P/E, EV/EBITDA, revenue growth, last refresh. | M1 |
| FR-WS-02 | Multi-ticker comparison view (secondary). | M9 |

## UX & Design (orig. §6)

### Design principles (orig. §6.1)
- **The data comes first.** The look is flat, dense and TradingView-like: hairline dividers, no cards and no shadows, minimal chrome.
- **Color only carries meaning**: green/red deltas, provenance badges, flag severity. Otherwise the palette is neutral gray.
- **Numbers**: tabular, monospaced digits, right-aligned. Auto-scaled (default millions) with a K/M/B toggle. Negatives shown in parentheses. Units and currency shown in the table header.
- **Provenance is always visible**: *as-reported*, *normalized* (adjusted), *derived* (e.g. Q4) and *forecast* cells are visually distinct, with a legend.
- **Theme**: dark and light, following the system preference, with a manual toggle.
- **Responsive**: usable at phone width. Tables scroll horizontally with a pinned first column, and the tab bar scrolls.

### Page map (orig. §6.2)
```
Login
Companies (home list)  ──►  Company page
Settings (units, theme, horizon defaults, API keys status)
```
Company page tabs: **Overview · Income · Balance · Cash Flow · Ratios · Valuation · Forecast · Scenarios · Backtest · Notes**
(Tabs belonging to later milestones are hidden until those milestones ship.)

### Company page layout (orig. §6.3)
```
┌──────────────────────────────────────────────────────────┐
│ AAPL  Apple Inc.   $231.40 +1.2%   Mkt cap 3.5T  ⟳ 2h ago │
├──────────────────────────────────────────────────────────┤
│ Overview  Income  Balance  Cash Flow  Ratios  Valuation ▸ │
│ ─────────                                                 │
│ [Annual|Quarterly|TTM]  [Reported|Normalized]  [M ▾]  ⤓  │
│                  FY21     FY22     FY23     FY24   FY25E  │
│ Revenue         365.8    394.3    383.3    391.0   410.2  │
│   YoY           33.3%     7.8%   (2.8%)     2.0%    4.9%  │
│ Gross profit    152.8    170.8    169.1    180.7   191.0  │
│ ...                                                       │
└──────────────────────────────────────────────────────────┘
 flat · hairline dividers · forecast columns tinted · E = estimate
```

### Charts (orig. §6.4)
Analytic charts only: ratio trend lines, forecast fan charts, tornado, scenario comparison, backtest error charts, seasonal decomposition. No price or technical charting.
