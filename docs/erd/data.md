# ERD · Data & Statements

> Split of [ERD.md](../ERD.md), originally §4 (data-layer tables, read paths), §5.1 (ingestion & statements flow), §6 (`DataSource` interface) and §7 (data-layer routes, statement payload).
> Product counterpart: [prd/data.md](../prd/data.md) (`FR-DATA`, `FR-STMT`). Cross-cutting data-model conventions (Decimal/units, period identity, UTC): [ERD.md §4](../ERD.md#4-data-model).
> Code: `backend/src/bedrock/{ingest,mapping,statements}/`, services `refresh_company`, `build_statements`.

## Tables (orig. §4)
| Table | Key columns | Notes |
|---|---|---|
| `company` | id, ticker (uq), cik (uq), name, fiscal_year_end_month, currency, sic, last_refreshed_at | |
| `filing` | id, company_id, accession_no (uq), form (10-K/10-Q/…), filed_at, fiscal_year, fiscal_period, period_end | One row per SEC filing seen |
| `raw_fact` | id, company_id, filing_id, taxonomy, concept, unit, period_start, period_end, fiscal_year, fiscal_period, frame, value | **Immutable, append-only.** Every vintage kept. uq(filing_id, taxonomy, concept, unit, period_start, period_end) |
| `canonical_item` | id, code (uq, e.g. `revenue`), statement (IS/BS/CF), label, kind (flow/instant), sign, display_order, parent_code | Seeded from `canonical_items.yaml` |
| `concept_mapping` | id, canonical_code, taxonomy, concept, priority, company_id NULL | `company_id NULL` = default mapping; non-null = per-company override (loaded from `overrides/<TICKER>.yaml`) |
| `adjustment` | id, company_id, canonical_code, fiscal_year, fiscal_period, amount, category (one-off/restatement/reclass/other), reason, created_at | Normalized = reported + Σ adjustments |
| `corporate_action` | id, company_id, type (split/reverse_split), effective_date, ratio | |
| `price_daily` | company_id, date, close, adj_close, volume | pk(company_id, date) |
| `shares_outstanding` | derived from raw_fact (dei:EntityCommonStockSharesOutstanding), split-adjusted in a view | |
| `macro_series` / `macro_observation` | series_id (FRED), title, frequency / series_id, date, value | M8. Consumed by Tier 4 ([erd/forecasting.md](forecasting.md)) |
| `segment_value` | id, company_id, segment_name, dimension (business/geo/kpi), metric, fiscal_year, fiscal_period, value, unit, source (manual) | M3 |
| `unmapped_concept` | view: raw_fact concepts with no mapping, for FR-DATA-04 | |

## Read paths (orig. §4)
- **Latest view**: for each (company, concept, unit, period), take the `raw_fact` from the filing with max `filed_at`.
- **Point-in-time view** `as_of(date)`: the same, restricted to `filing.filed_at ≤ date`. Used by the backtest (FR-ACC-03, [erd/accountability.md](accountability.md)).

## Ingestion & statements flow, M1–M2 (orig. §5.1)
```
refresh_company(ticker)
  → EDGAR: ticker→CIK (company_tickers.json) → companyfacts/CIK##########.json
      → cache raw JSON to data/raw/edgar/<cik>/<date>.json
      → upsert filing rows; insert new raw_fact rows (append-only, dedupe by uq key)
  → yfinance: daily prices since last date
  → mapper: raw_fact (latest or as-of) × concept_mapping (override > default, by priority)
      → canonical long frame [code, fy, fp, start, end, value, source_concept, accession]
  → statements: derive Q4 flows = FY − (Q1+Q2+Q3) ; YTD→discrete quarters for CF items
      → pivot to IS/BS/CF; apply adjustments → normalized
      → integrity check: assets = liabilities + equity (tolerance), flag failures
```

### EDGAR specifics (orig. §5.1)
- Every request sends `User-Agent: "Bedrock <SEC_USER_AGENT email>"`. A client-side token bucket keeps traffic ≤ 10 req/s. Retries with backoff on 429/5xx.
- Company facts contains only non-dimensional facts, so segment data is **not** available from it. Segments are manual in v1 (FR-DATA-11). Parsing XBRL dimensions from filing instances is a future milestone.
- The fiscal period comes from the `fy`/`fp`/`form`/`frame` fields. Cash-flow 10-Q values are year-to-date, so discrete quarters = YTD(Qn) − YTD(Qn−1).
- Canonical mapping: each canonical item lists ordered fallback concepts, e.g. `revenue: [RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, SalesRevenueNet]`. The first concept with a value for that period wins, and the source concept is recorded for provenance.

## Interface (orig. §6)
```python
# ingest/protocol.py
class DataSource(Protocol):
    name: ClassVar[str]
    def fetch(self, company: CompanyRef, since: date | None) -> SourcePayload: ...
```
Ingest adapters implement `DataSource` and are the only code that touches the network (layering rules: [ERD.md §1](../ERD.md#1-architecture-overview)).

## API (orig. §7)
- `GET/POST/DELETE /companies`, `POST /companies/{ticker}/refresh`
- `GET /companies/{ticker}/statements?type=IS&freq=annual&basis=normalized`
- `CRUD /companies/{ticker}/adjustments`
- Statement payloads use a long, column-oriented shape (`periods[]`, `rows[{code,label,values[],provenance[]}]`) that maps directly onto AG Grid.
