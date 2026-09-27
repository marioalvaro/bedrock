---
name: map-xbrl
description: Maps SEC XBRL concepts to Bedrock canonical line items, as defaults or per-company overrides. Use when a canonical item is unmapped or missing, a statement value disagrees with the 10-K, a balance sheet fails to balance, or a new ticker is onboarded.
---

# Map XBRL

Mapping design (canonical items, ordered fallback concepts, per-company overrides, provenance) is in [docs/erd/data.md](../../../docs/erd/data.md). Read it first.

## Companyfacts in brief
- `facts.<taxonomy>.<Concept>.units.<unit>[]` holds the values. Taxonomies are `us-gaap`, `dei` and occasionally company-specific ones (e.g. `aapl`).
- Each fact carries `start` (flows only), `end`, `val`, `accn`, `fy`, `fp`, `form` and `filed`.
- The same period appears in many filings. Those are **vintages**: the latest `filed` is the current value, and earlier ones are restatement history.
- `fy`/`fp` describe the *filing*, not the period. Identify a period by `start`/`end`.
- 10-Q cash-flow values are year-to-date.
- Companies change tags over time (e.g. `SalesRevenueNet` before 2018 → `RevenueFromContractWithCustomerExcludingAssessedTax`). An ordered fallback list bridges such tag changes.

## Tool
`.claude/skills/map-xbrl/scripts/xbrl_concepts.py` (stdlib only; `--help` for details):
- `fetch TICKER`: downloads into `data/raw/edgar/<cik>/<date>.json`. Needs `SEC_USER_AGENT`; if it is unset, ask the user for it rather than inventing one.
- `search FILE REGEX`: candidate concepts, with coverage and the latest annual values.
- `show FILE CONCEPT [--all-vintages]`: values by period.

## Steps
1. **Source.** Use the fixture `backend/tests/fixtures/edgar/<TICKER>.json`, else the newest file under `data/raw/edgar/<cik>/`, else `fetch`.
2. **Candidates.** `search` by name and label keywords for the item. List every plausible concept with its period coverage.
3. **Evidence.** Using `show`, compare each candidate for at least 3 fiscal years against the figure in the 10-K. When the 10-K number is not in hand, ask the user for it; never pick a concept on its name alone.
   - Watch the sign convention (payments reported as positive outflows).
   - Watch whether a concept is a subtotal or a component.
   - Watch for gaps where the company switched tags.
4. **Decide.**
   - A standard `us-gaap` concept that is correct for most companies becomes a **default** fallback, placed at the right priority.
   - A company-specific tag, or a choice that would be wrong elsewhere, becomes an **override** in `mapping/overrides/<TICKER>.yaml`.
   - When no single concept matches the 10-K (only components are reported), propose a derived item to the user instead of forcing a mapping.
5. **Write.** Edit `mapping/canonical_items.yaml` or the override file. Before M1 code exists, report the proposal instead.
6. **Test.** Add a regression test asserting the mapped value for at least two periods from the fixture. Re-run the statement invariant tests (A = L + E; Q1..Q4 = FY).

**Done when** every requested item is mapped with 10-K evidence and a passing test, or was escalated to the user with the reason.

## Report
Give a table with one row per canonical item: chosen concept(s) in priority order, default or override, the evidence (10-K value vs. mapped value per period), and open issues.
