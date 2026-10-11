# Bedrock

A personal web app for deep fundamental analysis of a handful of US companies, similar to TradingView's "Fundamentals" tab but with no price charts. Data comes from SEC EDGAR. On top of the raw statements it adds a forecasting and valuation layer that keeps the three statements accounting-consistent and scores past forecasts against actuals.

It is a single-user app: a FastAPI + SQLite backend and a React (Vite, TypeScript, Tailwind) SPA, in one repo.

> **Status:** milestone M1 (Data) is in progress: every implementation step is done, and the milestone's acceptance checks remain. M0 (scaffold: login, Docker, CI) is complete.

## Features

- **Follow companies by ticker.** Adding a ticker resolves it on SEC EDGAR, loads every filing's XBRL facts (all vintages, append-only) and daily prices from yfinance. A refresh loads only what is new.
- **Canonical statements.** Facts are mapped to about 80 canonical line items (`backend/src/bedrock/mapping/canonical_items.yaml`, plus per-company overrides) and shown as Income, Balance and Cash Flow statements, annual, quarterly or TTM. Q4 and missing quarters are derived from year-to-date figures, so Q1..Q4 always add up to the fiscal year.
- **Grid views.** YoY growth and common-size rows, collapsible subtotals, a balance check on every balance-sheet period and CSV export.
- **Provenance.** Each cell is marked reported or derived. Clicking a cell shows its source XBRL tag, the filing, the derivation formula and every filed vintage of the value.
- **Data gaps.** Each company's Overview lists items with no value in some year and concepts in the latest 10-K that nothing maps, with suggested canonical codes.
- **Company list** with price, market cap, P/E, EV/EBITDA and TTM revenue growth. Each stat is blank when an input is missing.

The test companies are AAPL, MSFT and COST.

## API

Every route is under `/api/v1`. Interactive docs are at `/docs` on a running backend.

| Method | Path | Auth | Response |
|---|---|---|---|
| `GET` | `/health` | public | `{"status": "ok"}` |
| `POST` | `/auth/login` | public | Body `{"password": "..."}`. Returns `204` and sets the `bedrock_session` cookie, or `401` for a wrong password, or `429` after 5 failures in 15 min. |
| `POST` | `/auth/logout` | public | `204` and clears the session |
| `GET` | `/auth/me` | session | `{"authenticated": true}`, or `401` |
| `GET` | `/companies` | session | The followed companies, each with its key stats |
| `POST` | `/companies` | session | Body `{"ticker": "AAPL"}`. Follows the company and loads its data: `201`, or `404` for an unknown ticker, `409` if already followed, `503` without `SEC_USER_AGENT`, `502` if a source fails. Nothing is kept if the first load fails. |
| `GET` | `/companies/{ticker}` | session | One followed company with its key stats, or `404` |
| `DELETE` | `/companies/{ticker}` | session | `204`. Removes the company and its stored data. |
| `POST` | `/companies/{ticker}/refresh` | session | Loads new filings and prices. Returns counts and warnings: a price failure is a warning, an EDGAR failure is an error. |
| `GET` | `/companies/{ticker}/statements` | session | Query `type=IS\|BS\|CF`, `freq=annual\|quarterly\|ttm`, optional `common_size_base=total\|parent`. Periods and rows with values, provenance, YoY and common size; a balance check for `BS`. `422` for a TTM balance sheet. |
| `GET` | `/companies/{ticker}/statements/cell` | session | Query `code`, `fiscal_year`, `fiscal_period` (`FY`, `Q1`..`Q4`). Where one value came from: source tag, filing, derivation and vintages. `404` for an unknown cell. |
| `GET` | `/companies/{ticker}/mapping-gaps` | session | Missing items and unmapped concepts |

Error responses carry a human-readable `{"detail": "..."}`.

A session expires after `SESSION_IDLE_MINUTES` of inactivity (default 720). In production, the backend also serves the built SPA: any other `GET` returns `index.html`.

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

Add companies from the web UI (the ticker box on the company list), or with the CLI:

```sh
cd backend
uv run bedrock add AAPL MSFT COST     # follow and load
uv run bedrock refresh --all          # or: refresh AAPL MSFT
uv run bedrock sync-mappings          # reload canonical_items.yaml and overrides/ into the DB
```

With Docker, run the same commands in the container, e.g. `docker compose exec app bedrock add AAPL`. Every command tries all tickers and exits `1` if any fails. Refresh also re-syncs the mappings, so YAML edits take effect on the next refresh.

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
