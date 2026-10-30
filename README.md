# Bedrock

A personal web app for deep fundamental analysis of a handful of US companies, similar to TradingView's "Fundamentals" tab but with no price charts. Data comes from SEC EDGAR. On top of the raw statements it adds a forecasting and valuation layer that keeps the three statements accounting-consistent and scores past forecasts against actuals.

It is a single-user app: a FastAPI + SQLite backend and a React (Vite, TypeScript, Tailwind) SPA, in one repo.

> **Status:** milestone M3 (Context) is in progress. M0 (scaffold), M1 (Data) and M2 (Analysis) are complete. Every planned M3 step (S1–S10d) is built; the manual browser checks that gate acceptance are still open. Forecasting, valuation models and backtesting (M4 onward) are not built yet.

New to the app? Read the [tutorial](TUTORIAL.md), a walkthrough of every screen.

## Features

- **Follow companies by ticker.** Adding a ticker resolves it on SEC EDGAR, loads every filing's XBRL facts (all vintages, append-only) and daily prices from yfinance. A refresh loads only what is new.
- **Canonical statements.** Facts are mapped to about 80 canonical line items (`backend/src/bedrock/mapping/canonical_items.yaml`, plus per-company overrides) and shown as Income, Balance and Cash Flow statements, annual, quarterly or TTM. Q4 and missing quarters are derived from year-to-date figures, so Q1..Q4 always add up to the fiscal year.
- **Grid views.** YoY growth and common-size rows, collapsible subtotals, a balance check on every balance-sheet period and CSV export.
- **Provenance.** Each cell is marked reported or derived. Clicking a cell shows its source XBRL tag, the filing, the derivation formula and every filed vintage of the value.
- **Data gaps.** Each company's Overview lists items with no value in some year and concepts in the latest 10-K that nothing maps, with suggested canonical codes.
- **Normalized basis.** Adjustments (one-offs, restructuring, impairments and so on) are stored apart from the as-reported data and flow through the income-statement waterfall and into balance-sheet and cash-flow subtotals. Cell details show each adjustment.
- **Splits.** Split history comes from yfinance and every share and per-share figure is adjusted by filing date.
- **Ratios.** A registry of ratios (profitability, returns, liquidity, leverage, efficiency, cash flow), annual or TTM, with caveats where a company's structure makes one misleading (for example DE's captive finance arm).
- **Valuation multiples.** P/E, P/B, P/S, P/FCF, EV multiples, yields and PEG, with the company's own historical range.
- **Quality of earnings.** Flags driven by thresholds you can edit in Settings, plus custom rules written as formulas, off-balance-sheet items and capital-allocation views.
- **Ratio details.** Clicking a ratio value shows its formula, numerator and denominator, and every input down to the statement lines.
- **Gap-filling rules.** Empty cells are filled where an accounting identity or the filing's own tags determine them (for example a total from its parts, or a non-controlling interest the filing never tags is 0). Q4 share counts and EPS are rebuilt, and shares outstanding fall back to issued less treasury or the cover-page count. Rules never replace a reported value, and a filled cell says how it was produced (muted 0, `~` for an approximation). Data gaps shows coverage, empty-cell causes and rule warnings.
- **Manual input.** Fill the gaps SEC leaves, or a whole company SEC does not cover, from an Excel or CSV template. A breakdown you add (for example a split of cost of revenue) becomes indented custom lines under its parent. See [Manual input](#manual-input).
- **Segments and KPIs.** Business and geographic segments (revenue or operating income, with an "Unallocated" row that reconciles to the statement) and your own KPIs, typed into a grid or pasted or uploaded as CSV. On the annual view, one button fills FY from the four quarters.
- **Comps.** Named peer sets of followed companies, with peers suggested by SIC code and size. Compares current multiples and the latest TTM ratios against the peer median and range.
- **Guidance log.** Enter a company's guidance (metric, period, low and high, date given). When the actual is reported it is scored beat, in range or miss on the reported or normalized basis, with a hit rate by metric.
- **Notes.** A Markdown thesis journal. A note can link to a statement line, a ratio, a capital-allocation metric, a quality rule, or a period. Linked cells carry a marker that opens their notes.
- **Company list** with price, market cap, P/E, EV/EBITDA and TTM revenue growth. Each stat is blank when an input is missing.

The test companies are AAPL, MSFT, COST and DE.

### Company tabs

Each company has these tabs: **Overview** (key stats, data gaps, adjustments, corporate actions), **Income**, **Balance**, **Cash Flow**, **Ratios**, **Quality**, **Capital**, **Segments**, **Comps**, **Guidance** and **Notes**. Settings holds the quality-of-earnings thresholds and custom rules.

## API

Every route is under `/api/v1`. Interactive docs are at `/docs` on a running backend.

| Method | Path | Auth | Response |
|---|---|---|---|
| `GET` | `/health` | public | `{"status": "ok"}` |
| `POST` | `/auth/login` | public | Body `{"password": "..."}`. Returns `204` and sets the `bedrock_session` cookie, or `401` for a wrong password, or `429` after 5 failures in 15 min. |
| `POST` | `/auth/logout` | public | `204` and clears the session |
| `GET` | `/auth/me` | session | `{"authenticated": true}`, or `401` |
| `GET` | `/companies` | session | The followed companies, each with its key stats |
| `POST` | `/companies/manual` | session | Body `{"ticker", "name", "fiscal_year_end_month", "sic"?}`. Creates a manual-only company (no SEC data, USD): `201`, or `409` if the ticker is already followed. |
| `POST` | `/companies` | session | Body `{"ticker": "AAPL"}`. Follows the company and loads its data: `201`, or `404` for an unknown ticker, `409` if already followed, `503` without `SEC_USER_AGENT`, `502` if a source fails. Nothing is kept if the first load fails. |
| `GET` | `/companies/{ticker}` | session | One followed company with its key stats, or `404` |
| `DELETE` | `/companies/{ticker}` | session | `204`. Removes the company and its stored data. |
| `POST` | `/companies/{ticker}/refresh` | session | Loads new filings and prices. Returns counts and warnings: a price failure is a warning, an EDGAR failure is an error. |
| `GET` | `/companies/{ticker}/statements` | session | Query `type=IS\|BS\|CF`, `freq=annual\|quarterly\|ttm`, optional `common_size_base=total\|parent`. Periods and rows with values, provenance, YoY and common size; a balance check for `BS`. `422` for a TTM balance sheet. |
| `GET` | `/companies/{ticker}/statements/cell` | session | Query `code`, `fiscal_year`, `fiscal_period` (`FY`, `Q1`..`Q4`). Where one value came from: source tag, filing, derivation and vintages. `404` for an unknown cell. |
| `GET` | `/companies/{ticker}/mapping-gaps` | session | Missing items and unmapped concepts |
| `GET` `POST` | `/companies/{ticker}/adjustments` | session | List or add adjustments |
| `PUT` `DELETE` | `/companies/{ticker}/adjustments/{id}` | session | Edit or remove an adjustment |
| `GET` | `/companies/{ticker}/corporate-actions` | session | Stored splits |
| `GET` | `/companies/{ticker}/ratios` | session | Ratios, annual or TTM, with caveats |
| `GET` | `/companies/{ticker}/ratios/cell` | session | How one ratio value was produced: formula, inputs, reason when empty |
| `GET` | `/companies/{ticker}/multiples` | session | Valuation multiples and own-history range |
| `GET` | `/companies/{ticker}/flags` | session | Quality-of-earnings flags |
| `GET` | `/companies/{ticker}/capital-allocation` | session | Capital-allocation breakdown |
| `GET` `POST` | `/companies/{ticker}/off-balance-items` | session | List or add off-balance-sheet items |
| `PUT` `DELETE` | `/companies/{ticker}/off-balance-items/{id}` | session | Edit or remove one |
| `GET` | `/companies/{ticker}/import-template` | session | Query `format=xlsx\|csv`, `prefill=false\|true`, `scale=units\|thousands\|millions\|billions`. Downloads the manual-input template. |
| `POST` | `/companies/{ticker}/imports` | session | Multipart `file` (10 MB at most), `dry_run` (default false), `scale?`. With `dry_run=true` returns the preview (cells to fill, ignored, unchanged, custom lines, warnings) and stores nothing. Otherwise stores the import. `422` lists every file error by sheet, row and column. |
| `GET` | `/companies/{ticker}/imports` | session | The import history, newest first |
| `DELETE` | `/companies/{ticker}/imports/{id}` | session | `204`. Removes that import's values and custom lines. |
| `GET` | `/companies/{ticker}/segments` | session | Segment and KPI grids, with the reconciliation row |
| `POST` `PUT` `DELETE` | `/companies/{ticker}/segment-series[/{id}]` | session | Add, rename or delete a series |
| `PUT` | `/companies/{ticker}/segment-series/{id}/values` | session | Set a series' values |
| `POST` | `/companies/{ticker}/segments/import` | session | Body `{dimension, text, scale}`. Imports CSV or TSV text. |
| `POST` | `/companies/{ticker}/segments/fill-annual` | session | FY = Q1+Q2+Q3+Q4 for USD series |
| `GET` `POST` | `/companies/{ticker}/comps-sets` | session | List or create peer sets |
| `PUT` `DELETE` | `/companies/{ticker}/comps-sets/{id}` | session | Rename, change members, or delete |
| `GET` | `/companies/{ticker}/peer-suggestions` | session | Followed companies ranked by SIC match, then size |
| `GET` | `/companies/{ticker}/comps-sets/{id}/comparison` | session | Multiples and ratios against the peer median and range |
| `GET` | `/companies/{ticker}/guidance/metrics` | session | The metrics guidance can be entered for |
| `GET` `POST` | `/companies/{ticker}/guidance` | session | List (with verdicts and hit rate) or add guidance |
| `PUT` `DELETE` | `/companies/{ticker}/guidance/{id}` | session | Edit or remove an entry |
| `GET` `POST` | `/companies/{ticker}/notes` | session | List (filterable) or add notes |
| `PUT` `DELETE` | `/companies/{ticker}/notes/{id}` | session | Edit or remove a note |
| `GET` | `/companies/{ticker}/notes/links` | session | Which cells and subjects have notes, for the markers |
| `GET` | `/qoe-rules` | session | QoE thresholds |
| `PUT` `DELETE` | `/qoe-rules/{code}` | session | Override or reset a threshold |
| `GET` `POST` | `/qoe-custom-rules` | session | List or add custom formula rules |
| `PUT` `DELETE` | `/qoe-custom-rules/{id}` | session | Edit or remove a custom rule |

Error responses carry a human-readable `{"detail": "..."}`.

A session expires after `SESSION_IDLE_MINUTES` of inactivity (default 720). In production, the backend also serves the built SPA: any other `GET` returns `index.html`.

## Manual input

SEC data has holes: a line a company never tags, years before XBRL, and companies that are not on EDGAR at all. Manual input fills them from an Excel or CSV file. It never touches `raw_fact`; imported values live in their own tables and are labelled **Imported** in the grids.

The rules to know:
- **An imported value only fills an empty cell.** An SEC value always wins, and if a later refresh fills a cell you had imported, SEC takes over by itself.
- **Imports feed the gap-filling rules.** Imported cells can complete a total, and an import counts as one filing, so SEC and imported numbers are never mixed in one solve.
- **Nothing is stored until you confirm.** The preview lists what would be filled, what is ignored and why, and any balance-sheet or cash-flow check that would break.
- **Every import is listed in History** and can be deleted; its cells fall back to SEC or an earlier import.
- Prices still come from yfinance. Imports cover the Income, Balance and Cash Flow statements, in USD.

### Fill the gaps of a followed company

1. Open the company and click **Import** on the Overview (next to Data gaps) or on any statement tab.
2. Under **1. Template** pick the format (Excel or CSV), the **Scale** your numbers are in, and tick **Prefill with current values** to see today's numbers, then **Download template**.
3. Fill it in (the layout is below) and save it.
4. Under **2. Upload and review** choose the file and click **Preview**. Read the counts, the ignored cells and any warnings.
5. Click **Import N cells**. The statements update straight away.

### Add a company SEC does not cover

1. On the company list, click **Add manual company**. Give a ticker, a name, the month the fiscal year ends and, optionally, a 4-digit SIC code (it feeds peer suggestions). Click **Create**.
2. Open it (it is tagged `manual` in the list) and follow the steps above. The calendar is built from the periods you import, and with no SEC data a blank template is all you need.

A manual company works like any other: ratios, quality, capital, comps, guidance and notes all run on its imported statements. Market cap uses the latest share count you imported. There is no CLI command for creating one.

### The template

The Excel template has an `Instructions` sheet and one sheet each for `IS`, `BS` and `CF`. A CSV template is one file with the same three sheets one after the other, every row led by its statement.

- **`Instructions`** holds `scale` and **`fiscal_year_end`**, the date your annual period ends (`2025-12-31`, or `2025-09-27` for a 52-week year). Every column's dates follow from this one date. It also has a filled example of each statement.
- **Statement sheets** have two header rows (`fiscal_year`, `fiscal_period`), a title row (`code`, `label`, `parent`, `unit`, `children_complete`, then the periods) and one row per line. The 100 period columns are the last 20 fiscal years: all the annual columns first, then the quarters (Q1 to Q4 of each year in turn), oldest first. Fill the columns you have and leave the rest blank.
- **Signs follow the statements**: capex, buybacks and the like are typed negative.
- **Scale** applies to USD amounts and share counts, never to per-share values.
- Grey rows (subtotals the app computes) are ignored with a warning if you type in them.
- To use exact dates for a 52/53-week year, add `period_start` and `period_end` rows above the title row; both or neither.

### Custom lines

To break a line down, add a row with a new label and set `parent` to the line it splits (a canonical line with no canonical children, or an earlier custom line). It shows indented under the parent with a **custom** marker, and an **Other** row shows the parent less the breakdown. If you mark the parent row `children_complete` = TRUE and the parent is empty, the sum of the custom lines fills it. If the parent already has a value and the breakdown does not add up, you get a warning and the parent keeps its value.

### Segments and KPIs

Segment and KPI breakdowns are a separate input on the **Segments** tab: type values into the grid, or click **Import** to paste or upload CSV or TSV. The sheet shows the format and a downloadable template.

The [tutorial](TUTORIAL.md#6-manual-input) walks through all of this with an example.

## Running

### 1. Configure

```sh
cp .env.example .env
cd backend && uv run bedrock hash-password   # paste the output into APP_PASSWORD_HASH
```

In `.env`:
- Set `APP_PASSWORD_HASH` to the hash, **wrapped in single quotes**. The hash contains `$`, and without quotes Docker Compose would expand it.
- Set `SESSION_SECRET`. The app refuses to start if it's blank. You can generate one with:
  ```sh
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- Set `SEC_USER_AGENT` to a contact email, e.g. `you@example.com`. The SEC requires one, and requests go out as `Bedrock <value>`. The app starts without it, but adding or refreshing a company fails with `503` until it is set.

Every variable is documented in `.env.example`.

### 2a. With Docker (recommended)

```sh
docker compose --profile prod up --build   # http://localhost:8000
docker compose --profile dev up --build    # http://localhost:5173
```

- The `prod` profile is a single container that serves both the API and the built SPA.
- The `dev` profile runs Vite with hot reload, proxying `/api` to a uvicorn backend that reloads when you edit backend code.
- Both run database migrations on start and keep the SQLite DB in `./data`.

### 2b. Without Docker

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 itself), Node 24 and pnpm 10.

```sh
# backend: http://localhost:8000
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn bedrock.main:create_app --factory --reload

# frontend: http://localhost:5173 (proxies /api to :8000)
cd frontend
pnpm install
pnpm dev
```

### 3. Add companies

Add SEC-covered companies from the web UI (the ticker box on the company list), or with the CLI. Companies SEC does not cover are added in the UI with **Add manual company** (see [Manual input](#manual-input)).

```sh
cd backend
uv run bedrock add AAPL MSFT COST     # follow and load
uv run bedrock refresh --all          # or: refresh AAPL MSFT
uv run bedrock sync-mappings          # reload canonical_items.yaml and overrides/ into the DB
```

With Docker, run the same commands in the container, e.g. `docker compose exec app bedrock add AAPL`. `refresh --all` also covers manual companies (prices only). Every command tries all tickers and exits `1` if any fails. Refresh also re-syncs the mappings, so YAML edits take effect on the next refresh.

The raw EDGAR responses are cached under `DATA_DIR/raw/edgar/`, and they stay there when a company is removed.

## Tests and checks

These are the same commands CI runs (`.github/workflows/ci.yml`).

```sh
# backend
cd backend
uv run pytest            # unit, engine and API tests: recorded fixtures, temporary SQLite, no network
uv run ruff check . && uv run ruff format --check .
uv run mypy src

# frontend
cd frontend
pnpm test                # Vitest
pnpm lint && pnpm typecheck && pnpm build
```

### API client drift

The frontend's API client is generated from the backend's OpenAPI schema. After changing an endpoint, regenerate it and commit the result. CI fails if they disagree.

```sh
cd backend && uv run bedrock export-openapi ../frontend/openapi.json
cd ../frontend && pnpm gen:api
```

### Live tests and fixtures

Tests marked `live` hit the real SEC and yfinance and are skipped by default. They need `SEC_USER_AGENT`.

```sh
cd backend
uv run pytest -m live
uv run python scripts/record_fixtures.py AAPL MSFT COST   # re-record tests/fixtures/ from the real sources
```

The golden tests (`tests/golden/statements/`) compare the mapped statements with figures taken from the 10-K documents, so a re-recorded fixture must still match them.

### Mappings

`mapping/canonical_items.yaml` defines the line items and the default XBRL concepts for each one. `mapping/overrides/<TICKER>.yaml` holds company-specific choices. To fix an unmapped or wrong item, use the `map-xbrl` skill. Candidate codes in Data gaps come from a vendored edgartools table, which you can update with `uv run python scripts/update_edgartools_mappings.py <tag>`.

Backend code is written test-first. The backend tests don't depend on your environment or `.env`: the test settings pin every value.

## License

MIT. See [LICENSE](LICENSE).
