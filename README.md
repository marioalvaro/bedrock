# Bedrock

A personal web app for deep fundamental analysis of a handful of US companies, similar to TradingView's "Fundamentals" tab but with no price charts. Data comes from SEC EDGAR. On top of the raw statements it adds a forecasting and valuation layer that keeps the three statements accounting-consistent and scores past forecasts against actuals.

It is a single-user app: a FastAPI + SQLite backend and a React (Vite, TypeScript, Tailwind) SPA, in one repo.

> **Status (2026-11-20):** M0 (scaffold) through M7d are built: statements, analysis, scenarios and forecasts, valuation (M5), statistical forecast engines (M6), snapshots, backtesting and the audit log (M7), data coverage (M7b) and the as-reported view with optional AI line classification (M7d). M7c (Closing the loop) is built (S1–S9): new-filing detection, automatic snapshots, the earnings review, thesis checkpoints, and the workspace polish (archive instead of delete, two-level tabs, a Data tab, a company switcher, a summary Overview, analytic charts and a comparison view). Browser acceptance and CI runs are still open for M5 onward. Macro and later milestones (M8+) are not built yet.

New to the app? Read the [tutorial](TUTORIAL.md), a walkthrough of every screen.

## Features

- **Follow companies by ticker.** Adding a ticker resolves it on SEC EDGAR, loads every filing's XBRL facts (all vintages, append-only) and daily prices from yfinance. A refresh loads only what is new.
- **Canonical statements.** Facts are mapped to about 80 canonical line items (`backend/src/bedrock/mapping/canonical_items.yaml`, plus per-company overrides) and shown as Income, Balance and Cash Flow statements, annual, quarterly or TTM. Q4 and missing quarters are derived from year-to-date figures, so Q1..Q4 always add up to the fiscal year.
- **Grid views.** YoY growth and common-size rows, collapsible subtotals, a balance check on every balance-sheet period and CSV export.
- **Provenance.** Each cell is marked reported or derived. Clicking a cell shows its source XBRL tag, the filing, the derivation formula and every filed vintage of the value.
- **Data gaps.** Each company's Data tab lists items with no value in some year and concepts in the latest 10-K that nothing maps, with suggested canonical codes.
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
- **Guidance log.** Enter a company's guidance (metric, period, low and high, date given). When the actual is reported it is scored beat, in range or miss on the reported or normalized basis, with a hit rate by metric. A bar chart compares, one metric at a time (annual or quarterly), the actuals of the last two years or four quarters against management guidance, the analyst consensus (its range as whiskers) and your own Base-case forecast.
- **Notes.** A Markdown thesis journal. A note can link to a statement line, a ratio, a capital-allocation metric, a quality rule, or a period. Linked cells carry a marker that opens their notes.
- **Scenarios and drivers.** Each company has scenarios (one default, plus your own), each with a Base, Bull and Bear case. A case is a set of drivers (revenue growth or a segment / volume × price build, margins, working-capital days, capex, buybacks, …) for 5 forecast years, by year or by quarter for the next 8 quarters. Defaults come from recent history. Bull and Bear follow Base, either with their own values or as offsets ("Base + 3 pts"). Drivers can be exported to and imported from CSV or Excel.
- **Forecast.** The drivers build all three statements, accounting-consistent: the balance sheet balances, and cash and retained earnings roll forward. Q1..Q4 add up to each fiscal year. An integrity panel shows every check per period, and a comparison charts Bull, Base and Bear side by side.
- **Valuation.** For each case: a DCF on free cash flow to the firm (a WACC from manual inputs or a direct rate; a Gordon-growth or exit-multiple terminal value, each with the other's implied figure; the bridge from EV to value per share). Next to it, multiple targets: P/E, EV/EBITDA, P/FCF or EV/Sales on a forecast year, with a manual multiple, a percentile of the company's own history or a peer median. Each method's target price and upside are shown against the latest close, and Bull, Base and Bear side by side. Inputs are set per case; Bull and Bear inherit Base's until they set their own.
- **Sensitivity.** A tornado ranks every driver and the discount rate, terminal growth or exit multiple by how much one unit step moves the DCF value per share (±1 pt, ±5 days, ±10 %, ±0.5 pt, ±1×). A 5 × 5 grid shows the value over any two of those inputs.
- **Statistical forecast engines.** A driver you have not set takes a default from a statistical engine: **Auto** (the engine with the lowest holdout error), 3-year **Mean**, **ARIMA**, **ETS**, a **Blend**, or **STL** for seasonal quarterly lines. Pick the engine per driver and scenario; the Engines sheet charts each engine's forecast beside the history with a 90 % range, and a forecast value outside that range is underlined in the driver grid.
- **Seasonality.** An STL decomposition of a quarterly line (observed and trend, seasonal, residual), its seasonal strength and the Q1..Q4 seasonal factors. Quarterly forecasts can follow the seasonal index.
- **Snapshots and backtesting.** Save a scenario's Bull, Base and Bear as a snapshot that can never change; each is scored against the actuals as they land (error, MAPE, bias, hit rate). The backtest reruns every engine from the last 10 10-K dates on the data known at each date (point in time, so restatements are respected) and scores them by horizon.
- **Audit log.** Every change to a driver, engine, year mode, valuation input, scenario or adjustment, and every line-classification decision, is logged with its old and new value and time; you can add a rationale to any row afterwards.
- **Data coverage.** Coverage is measured strictly and on applicable cells, every empty cell names its cause, and **Read all filings** reads each 10-K and 10-Q's own XBRL (extension tags and the lines on the face of the statements) in the background. A line a company reports merged with another is shown on the main row with a marker, and the other row reads "incl. in …"; a line that cannot exist in a period reads "n/a".
- **As reported.** Any filing's statement in the company's own lines, labels and order, with each line's Bedrock row and a mark on a total that does not equal the sum of its lines. Read only.
- **AI line classification (optional).** With your own Anthropic, TypeSafe (Jev) or OpenRouter API key, lines nothing else classifies can be sent to a classifier, only from a button and after a confirmation of the lines, tokens and cost. Each answer is a proposal you accept, reject or replace; a per-company switch (Off, Accepted only, All above 90 %) sets what the statements use. Classified answers only fill empty cells, never move a subtotal, and are marked. Daily and monthly token budgets cap spending. Without a key the feature is absent.
- **New filings are announced.** Once a day the app reads each company's EDGAR filing index and marks a company with a 10-K or 10-Q that is not loaded yet, on the company list and in its header. Nothing is loaded until you click Refresh.
- **Automatic snapshot.** When a refresh is about to store a new 10-K or 10-Q, the default scenario is snapshotted first, on the data before the filing, so every report is scored against what you expected.
- **Earnings review.** One page for the newest report: actual against the snapshot taken before it (with the Bear–Bull range), the analyst consensus and management guidance for seven key lines, the drivers that missed most, the prior values the filing restated, and the quality flags and thesis checkpoints that changed state.
- **Thesis checkpoints.** Testable statements of your thesis in the formula language, such as `gross_margin > 44%` or `net_debt_to_ebitda <= 2`, each shown as Holding, At risk, Broken or Unknown on the latest data, with what the last filing changed.
- **Scheduled refresh.** Prices refresh hourly in US market hours, and the market series (risk-free rate, equity risk premium) and analyst consensus once a day. Filings stay behind Refresh.
- **Company list** with price, market cap, P/E, EV/EBITDA and TTM revenue growth. Each stat is blank when an input is missing.
- **Archive instead of delete.** A company is archived from the list (with an Undo) and restored from the Archived table. A scheduled refresh skips an archived company. Permanent deletion is a second step: the dialog lists what is lost (filings, facts, notes, scenarios, snapshots, …) and needs the ticker typed.
- **Overview summary.** Seven key metrics over five years with sparklines and year-on-year change, the open quality flags, the value range against the price, how fresh the forecast is, and the latest notes.
- **Analytic charts.** Ratio trend lines (pick up to five ratios), capital-allocation bars, backtest error by horizon, and a forecast-against-history line.
- **Comparison view.** Two to six followed companies side by side: key stats and summary metrics in a table, and one metric charted over five fiscal years.
- **Company switcher.** The ticker in a company's header opens a filterable list to jump to another company on the same tab.

The test companies are AAPL, MSFT, COST and DE.

### Company tabs

Each company has these tabs, grouped by function:

Two levels: a bar of groups, and under it the tabs of the active group (hidden for a group with one tab). The URLs (`/c/<ticker>/<tab>`) do not depend on the group.

| Group | Tabs |
|---|---|
| **Overview** | Overview |
| **Financials** | Income · Balance · Cash Flow · Segments · Data |
| **Analysis** | Ratios · Capital · Quality · Seasonality · Comps |
| **Model** | Guidance · Scenarios · Forecast · Valuation |
| **Track** | Backtest · Review |
| **Notes** | Notes |

- **Overview**: a summary: key stats, key metrics with sparklines, open flags, valuation range, forecast freshness and the latest notes.
- **Data**: data gaps (with the lines to classify), adjustments and corporate actions.
- **Backtest** has three views: Backtest, Snapshots and Audit log. **Review** is the earnings review of the newest report. **Notes** holds the thesis checkpoints above the journal.
- Valuation, Forecast and Scenarios share the picked scenario and case (`?scenario=<id>&case=base|bull|bear`).

Settings holds the quality-of-earnings thresholds, custom rules, the formula reference and the classifier status.

## API

Every route is under `/api/v1`. Interactive docs are at `/docs` on a running backend.

| Method | Path | Auth | Response |
|---|---|---|---|
| `GET` | `/health` | public | `{"status": "ok"}` |
| `POST` | `/auth/login` | public | Body `{"password": "..."}`. Returns `204` and sets the `bedrock_session` cookie, or `401` for a wrong password, or `429` after 5 failures in 15 min. |
| `POST` | `/auth/logout` | public | `204` and clears the session |
| `GET` | `/auth/me` | session | `{"authenticated": true}`, or `401` |
| `GET` | `/companies` | session | The followed companies, each with its key stats. Query `archived=true` lists the archived ones instead. |
| `POST` | `/companies/manual` | session | Body `{"ticker", "name", "fiscal_year_end_month", "sic"?}`. Creates a manual-only company (no SEC data, USD): `201`, or `409` if the ticker is already followed. |
| `POST` | `/companies` | session | Body `{"ticker": "AAPL"}`. Follows the company and loads its data: `201`, or `404` for an unknown ticker, `409` if already followed or archived, `503` without `SEC_USER_AGENT`, `502` if a source fails. Nothing is kept if the first load fails. |
| `GET` | `/companies/{ticker}` | session | One followed company with its key stats, or `404` |
| `POST` | `/companies/{ticker}/archive` | session | `204`. Archives the company (a no-op if archived). The scheduler and `--all` commands skip it; nothing is deleted. |
| `POST` | `/companies/{ticker}/restore` | session | `204`. Follows an archived company again. No re-ingestion. |
| `GET` | `/companies/{ticker}/deletion-impact` | session | Counts of what a permanent delete removes: filings, facts, notes, scenarios, snapshots, guidance, adjustments, checkpoints, comps sets, imports |
| `DELETE` | `/companies/{ticker}` | session | `204`. Removes the company and its stored data; `409` unless the company is archived first. |
| `GET` | `/companies/{ticker}/summary` | session | The Overview summary: seven key metrics over five years, open flags, valuation range, forecast freshness, latest notes, and a warning for any block that could not be computed |
| `POST` | `/companies/{ticker}/refresh` | session | Loads new filings and prices. Returns counts and warnings: a price failure is a warning, an EDGAR failure is an error. When a new 10-K or 10-Q is about to be stored, the default scenario is snapshotted first and `snapshot_id` names it (null otherwise). |
| `POST` | `/companies/{ticker}/backfill-filings` | session | `202`. Reads the XBRL of every 10-K and 10-Q not read yet, in the background; progress is `filings_parsed` of `filings_total` on the company. `409` while one runs. |
| `GET` | `/companies/{ticker}/statements` | session | Query `type=IS\|BS\|CF`, `freq=annual\|quarterly\|ttm`, optional `common_size_base=total\|parent`. Periods and rows with values, provenance, YoY and common size; a balance check for `BS`. `422` for a TTM balance sheet. |
| `GET` | `/companies/{ticker}/statements/cell` | session | Query `code`, `fiscal_year`, `fiscal_period` (`FY`, `Q1`..`Q4`). Where one value came from: source tag, filing, derivation and vintages. `404` for an unknown cell. |
| `GET` | `/companies/{ticker}/mapping-gaps` | session | Coverage (strict and applicable), empty-cell causes, rule warnings, missing items, unmapped concepts and lines to classify |
| `GET` | `/companies/{ticker}/as-reported` | session | Query `statement`, optional `accession` (default the newest 10-K). One filing's statement as filed, with each line's Bedrock row and the totals that do not foot. |
| `GET` | `/classification/status` | session | The classifiers, whether each has its key, the token budgets and what was used |
| `GET` `PUT` | `/companies/{ticker}/classifications` | session | The lines to classify with their answers (query `classifier` adds what a run would ask and its estimate), or store your own answer for one line |
| `POST` | `/companies/{ticker}/classifications/run` | session | `202`. Asks a classifier about the open lines, after the confirmation; sends their labels, tags and amounts to the provider. `409` without a key, while a run runs, or over budget. |
| `PUT` | `/companies/{ticker}/classifications/{id}` | session | Accept, reject or reopen one answer |
| `PUT` | `/companies/{ticker}/classification-mode` | session | What the statements use: `off`, `accepted` or `all` (above the confidence threshold) |
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
| `GET` | `/companies/{ticker}/guidance/consensus` | session | The analyst consensus estimates as placed on fiscal periods (logged as read-only guidance entries) |
| `GET` | `/companies/{ticker}/guidance/history` | session | Every actual of one metric (`metric`, `basis`, `freq`), oldest first, for the Guidance chart |
| `GET` `POST` | `/companies/{ticker}/guidance` | session | List (with verdicts and hit rate) or add guidance |
| `PUT` `DELETE` | `/companies/{ticker}/guidance/{id}` | session | Edit or remove an entry |
| `GET` `POST` | `/companies/{ticker}/notes` | session | List (filterable) or add notes |
| `PUT` `DELETE` | `/companies/{ticker}/notes/{id}` | session | Edit or remove a note |
| `GET` | `/companies/{ticker}/notes/links` | session | Which cells and subjects have notes, for the markers |
| `GET` `POST` | `/companies/{ticker}/checkpoints` | session | The thesis checkpoints with their state now and before the newest report, or add one (`{statement, label?, freq?: ttm\|annual, margin?}`); `422` names the position of a statement error |
| `PUT` `DELETE` | `/companies/{ticker}/checkpoints/{id}` | session | Edit or remove a checkpoint |
| `GET` `POST` | `/companies/{ticker}/scenarios` | session | List the scenarios, or create one (name and revenue build); it starts from the default drivers |
| `PUT` `DELETE` | `/companies/{ticker}/scenarios/{id}` | session | Rename or change the revenue build, or delete (not the default scenario) |
| `GET` | `/companies/{ticker}/scenarios/{id}/years` | session | Whether each year of the quarterly span is set annually or by quarter |
| `PUT` | `/companies/{ticker}/scenarios/{id}/years/{fiscal_year}/mode` | session | Body `{"mode": "annual"\|"quarterly"}`. Back to annual deletes the quarter values of all three cases. |
| `GET` `PUT` | `/companies/{ticker}/scenarios/{id}/cases/{case}/drivers` | session | Query `freq=annual\|quarterly`. The case's driver grid with each value's source, or set rows of values or offsets. `case` is `base`, `bull` or `bear`. |
| `POST` | `/companies/{ticker}/scenarios/{id}/cases/{case}/reset` | session | The case's drivers go back to their defaults (valuation inputs are left alone) |
| `GET` | `/companies/{ticker}/scenarios/{id}/cases/{case}/drivers/export` | session | Query `format=csv\|xlsx`. Downloads the case's drivers. |
| `POST` | `/companies/{ticker}/scenarios/{id}/cases/{case}/drivers/import` | session | Multipart `file`, `dry_run`. Previews or applies a driver file; `422` lists each error by row and column. |
| `GET` | `/companies/{ticker}/scenarios/{id}/cases/{case}/forecast` | session | Query `type=IS\|BS\|CF`, `freq`. Actual and forecast periods with the integrity checks; `422` "Set these drivers: …" when a required driver is missing. |
| `GET` | `/companies/{ticker}/scenarios/{id}/compare` | session | Query `freq`. The three cases' key lines side by side |
| `GET` `PUT` | `/companies/{ticker}/scenarios/{id}/engines` | session | The engine chosen per driver for the scenario (`auto`, `mean`, `arima`, `ets`, `blend`, `stl`), or set some |
| `GET` | `/companies/{ticker}/scenarios/{id}/cases/{case}/driver-engines` | session | Query `code`. One driver's history and every engine's forecast, holdout error and 90 % range |
| `GET` | `/companies/{ticker}/seasonality` | session | Query `code` (default revenue). The STL decomposition of a quarterly line, its strength and seasonal factors |
| `GET` `PUT` | `/companies/{ticker}/scenarios/{id}/cases/{case}/valuation-inputs` | session | The case's valuation inputs with their sources (own, inherited from Base, default, derived), or set rows `{"code", "value"}`; `null` clears one. Every row is checked before anything is stored. |
| `POST` | `/companies/{ticker}/scenarios/{id}/cases/{case}/valuation-inputs/reset` | session | Removes the case's own inputs |
| `GET` | `/companies/{ticker}/scenarios/{id}/cases/{case}/valuation` | session | The DCF and multiple-target results, the bridge and the price. A method that cannot value carries its `error`; `422` when the forecast cannot run. |
| `GET` | `/companies/{ticker}/scenarios/{id}/valuation` | session | Value per share and upside by method for Bull, Base and Bear |
| `GET` | `/companies/{ticker}/scenarios/{id}/cases/{case}/sensitivity/tornado` | session | Each input's DCF value per share one step lower and higher, sorted by range |
| `GET` | `/companies/{ticker}/scenarios/{id}/cases/{case}/sensitivity/grid` | session | Query `x`, `y` (input codes). The 5 × 5 DCF value per share; `422` for the same input twice or an unknown one. |
| `POST` | `/companies/{ticker}/scenarios/{id}/snapshots` | session | Body `{"note"?}`. Freezes the scenario's three cases and their valuations: `201` |
| `GET` | `/companies/{ticker}/snapshots` | session | The snapshots, newest first, with their scores and the aggregate scores |
| `GET` | `/companies/{ticker}/snapshots/{id}` | session | One snapshot's frozen cases scored against the latest actuals |
| `GET` `POST` | `/companies/{ticker}/backtest` | session | The last backtest's origins and scores, or run it again (about 15 s) |
| `GET` | `/companies/{ticker}/audit` | session | Query `entity?`, `limit?`, `before_id?`. The audit log, newest first, one page at a time |
| `PATCH` | `/companies/{ticker}/audit/{id}` | session | Body `{"rationale"}`. Sets or clears a row's rationale (500 characters at most) |
| `GET` | `/companies/{ticker}/earnings-review` | session | The newest 10-K or 10-Q against the snapshot taken before it: key lines with consensus and guidance, driver misses, restated values, changed flags and checkpoints |
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

1. Open the company and click **Import** on the Overview or the Data tab or on any statement tab.
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

Optional:
- `FRED_API_KEY`: the valuation's risk-free rate defaults to FRED's 10-year Treasury yield (else the yfinance `^TNX` yield).
- `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY`: each enables its line classifiers (Claude Haiku and Sonnet; Jev; the OpenRouter models). `CLASSIFY_DAILY_TOKENS`, `CLASSIFY_MONTHLY_TOKENS`, `CLASSIFY_MAX_LINES_PER_RUN` and `CLASSIFY_MIN_CONFIDENCE` cap and tune them. Set a spending limit in the provider's console as well: these budgets only limit this app.
- `SCHEDULED_REFRESH=false` turns off the hourly prices, the daily market series and consensus, and the daily new-filing check.

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
uv run bedrock backfill-filings AAPL  # read every 10-K and 10-Q's own XBRL (or --all; --reparse re-reads)
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
