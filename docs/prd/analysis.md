# PRD · Analysis

> Split of [PRD.md](../PRD.md), originally §5.3 (Analysis).
> Engineering counterpart: [erd/analysis.md](../erd/analysis.md). Milestones and acceptance criteria: [PRD.md §8](../PRD.md#8-milestone-roadmap).
> Use cases served: UC-2, UC-7, UC-9.

## Analysis — `ANL` (orig. §5.3)
| ID | Requirement | M |
|---|---|---|
| FR-ANL-01 | Profitability ratios: gross/operating/net/FCF margins, ROE, ROA, ROIC, DuPont breakdown. | M2 |
| FR-ANL-02 | Liquidity ratios: current, quick. Solvency: debt/EBITDA, net debt/EBITDA, interest coverage, debt/equity. | M2 |
| FR-ANL-03 | Efficiency: asset turnover, DSO, DIO, DPO, cash conversion cycle. | M2 |
| FR-ANL-04 | Per-share metrics: EPS, FCF/share, BVPS, dividends/share, split-adjusted. | M2 |
| FR-ANL-05 | Quality-of-earnings flags: accruals ratio, CFO vs. net income divergence, DSO or inventory growing faster than revenue, goodwill as % of assets and impairments, SBC as % of revenue/CFO; manually logged off-balance-sheet items (leases, guarantees, VIEs). Each flag states its rule and threshold. | M2 |
| FR-ANL-06 | Capital allocation: buybacks, dividends, net share-count change (dilution/accretion), capex vs. D&A, acquisitions; shown as history and as % of CFO/FCF. | M2 |
| FR-ANL-07 | Valuation multiples (P/E, EV/EBITDA, P/S, P/FCF, EV/Sales) with the company's own historical range (min/median/max, percentile). | M3 |
| FR-ANL-08 | Comps sets: a named peer group per company. Multiples and key ratios compared with peer median and range. | M3 |
| FR-ANL-09 | Guidance log: enter guidance (metric, period, low/high, date given). Compared to actuals when reported, with a hit/miss history. | M3 |
