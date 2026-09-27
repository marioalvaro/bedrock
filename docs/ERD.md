# Bedrock — Engineering Requirements Document

> **How** Bedrock is built. For *what* and *why*, see [PRD.md](PRD.md). Requirement IDs (`FR-…`) refer to the PRD.
> This document is the engineering source of truth: when an architectural decision changes, update it here first.
> **Structure**: this file is the index and holds the cross-cutting sections (architecture, stack, structure, data-model conventions, API conventions, coding conventions). Area-specific tables, flows, interfaces and routes live in one file per area under [erd/](erd/). Each split names the original section it came from.

## Area files

| Area | ERD split | PRD counterpart | Contents |
|---|---|---|---|
| Data & Statements | [erd/data.md](erd/data.md) | [prd/data.md](prd/data.md) | data-layer tables, read paths (latest / point-in-time), ingestion flow, EDGAR specifics, `DataSource`, statement routes & payload |
| Analysis | [erd/analysis.md](erd/analysis.md) | [prd/analysis.md](prd/analysis.md) | comps & guidance tables, ratio registry, analysis routes |
| Forecasting | [erd/forecasting.md](erd/forecasting.md) | [prd/forecasting.md](prd/forecasting.md) | scenario/driver/forecast tables, forecast→valuation flow, `ForecastEngine`, `DriverModel` + Tier 1 integrity rules, Tier 5 |
| Valuation | [erd/valuation.md](erd/valuation.md) | [prd/valuation.md](prd/valuation.md) | `valuation_run`, `ValuationMethod`, sensitivity |
| Accountability | [erd/accountability.md](erd/accountability.md) | [prd/accountability.md](prd/accountability.md) | backtest & audit tables, snapshot/backtest flow |
| Workspace & Frontend | [erd/workspace.md](erd/workspace.md) | [prd/workspace.md](prd/workspace.md) | `note` table, notes routes, API client codegen |
| Auth | [erd/auth.md](erd/auth.md) | [prd/auth.md](prd/auth.md) | login/session design, auth routes |
| Platform | [erd/platform.md](erd/platform.md) | [PRD.md §7](PRD.md#7-non-functional-requirements) | env config, testing strategy, CI, Docker, deploy, backups |

## 1. Architecture Overview

```
 Browser (phone / tablet / laptop)
 ┌──────────────────────────────────────────┐
 │ React SPA (Vite, TS)                      │
 │  shadcn/ui · AG Grid · ECharts            │
 │  TanStack Query ◄── generated TS client   │
 └───────────────┬──────────────────────────┘
                 │ JSON over HTTPS  /api/v1  (session cookie)
 ┌───────────────▼──────────────────────────┐        ┌──────────────┐
 │ FastAPI                                   │        │ CLI (Typer)  │
 │  api/ routers  (thin: validate, call)     │        └──────┬───────┘
 │        │                                  │               │
 │  services/  (use-cases, transactions) ◄───┼───────────────┘
 │        │                                  │
 │  domain engines (pure, pandas):           │
 │   mapping · statements · ratios · analysis│
 │   forecast (tier1..5) · valuation · backtest
 │        │                                  │
 │  repositories (SQLAlchemy)                │
 │  ingest adapters: EDGAR · yfinance · FRED │──► external APIs
 └───────────────┬──────────────────────────┘
                 │
            SQLite file  (+ raw JSON cache on disk)
```

**Layering rules**
- Routers and the CLI call **services** only. Services own transactions and orchestrate repositories, adapters and engines.
- **Domain engines are pure**: DataFrames and dataclasses in, results out. They do no DB access and no network. This is where TDD applies most.
- **Ingest adapters** implement the `DataSource` protocol and are the only code that touches the network.
- The same service functions back both the API and the CLI (e.g., `refresh_company`).

## 2. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language (backend) | Python 3.12 | User's strongest language; the finance and stats ecosystem is Python |
| Packaging | uv | Fast, lockfile, manages the Python version |
| Web framework | FastAPI + Uvicorn | Typed, generates OpenAPI (drives frontend codegen) |
| Schemas | Pydantic v2 | API I/O and config (`pydantic-settings`) |
| ORM / migrations | SQLAlchemy 2.0 (typed ORM) + Alembic | Portable to Postgres later |
| Database | SQLite (WAL mode) | Single file, zero-config, plenty for personal scale |
| Data | pandas | Native fit with statsmodels and yfinance; data sizes are tiny |
| Stats | statsmodels | ARIMA, ETS, STL, OLS. Prophet may be added later as a plug-in engine |
| Numerics | numpy | Monte Carlo |
| HTTP | httpx | EDGAR/FRED clients, with rate limiting and retries |
| Prices | yfinance | Daily prices, cross-check |
| Excel I/O | openpyxl | Driver import/export |
| CLI | Typer | `bedrock refresh AAPL`, etc. |
| Auth | argon2-cffi + signed session cookie (itsdangerous / Starlette SessionMiddleware) | Single user |
| Backend quality | pytest, ruff (lint+format), mypy (strict on domain packages) | |
| Frontend | Vite + React + TypeScript (strict) | |
| UI kit | shadcn/ui (Radix) + Tailwind CSS | Flat and minimal; component code lives in the repo |
| Grid | AG Grid Community | Pinned columns, cell editing, copy/paste, CSV export |
| Charts | Apache ECharts (`echarts-for-react`) | Fan, tornado, line/bar, dark mode |
| Server state | TanStack Query | Caching and refetching |
| Routing | React Router | |
| API client | `@hey-api/openapi-ts` + `@hey-api/client-fetch`, generated from FastAPI's OpenAPI (exported to `frontend/openapi.json`) | Types never drift from the backend |
| Frontend quality | ESLint, Prettier, Vitest | |
| Package manager (frontend) | pnpm | |
| Runtime | Docker Compose (dev + prod profiles) | Laptop first, home server later |
| CI | GitHub Actions | Lint, typecheck, tests, OpenAPI client-drift check |

## 3. Project Structure

```
bedrock/
├── CLAUDE.md
├── docs/                       PRD.md · ERD.md (indexes) · prd/ · erd/ (area splits) · progress/ (CURRENT.md + archive/) · brainstorm.md
├── docker-compose.yml
├── .github/workflows/ci.yml
├── backend/
│   ├── pyproject.toml · uv.lock · alembic.ini · Dockerfile
│   ├── migrations/
│   ├── src/bedrock/
│   │   ├── main.py               FastAPI app factory
│   │   ├── cli.py                Typer entrypoint
│   │   ├── core/                 config (settings), db (engine/session), auth, logging, units
│   │   ├── models/               SQLAlchemy ORM models
│   │   ├── repositories/         query functions per aggregate (incl. point-in-time)
│   │   ├── schemas/              Pydantic API schemas
│   │   ├── api/v1/               routers: auth, companies, statements, ratios, forecasts, ...
│   │   ├── services/             use-cases: refresh_company, build_statements, run_forecast, ...
│   │   ├── ingest/               sources/{edgar,yfinance,fred}.py · protocol.py · cache.py
│   │   ├── mapping/              canonical_items.yaml · overrides/<TICKER>.yaml · mapper.py
│   │   ├── statements/           canonical statement assembly, Q4 derivation, TTM, normalization
│   │   ├── ratios/               ratio definitions (registry) + calculator
│   │   ├── analysis/             qoe.py · capital_allocation.py · multiples.py · comps.py
│   │   ├── forecast/             interface.py · registry.py · engines/{driver,arima,ets,stl,macro,montecarlo}.py
│   │   ├── valuation/            interface.py · registry.py · dcf.py · multiples.py · sensitivity.py
│   │   └── backtest/             snapshot.py · scoring.py
│   └── tests/
│       ├── fixtures/edgar/       recorded companyfacts JSON (AAPL, MSFT, COST, DE)
│       ├── golden/               expected ratio/statement values
│       ├── unit/ · integration/
│       └── conftest.py
└── frontend/
    ├── package.json · pnpm-lock.yaml · vite.config.ts · tailwind.config.ts · Dockerfile
    └── src/
        ├── api/generated/        codegen output (do not hand-edit)
        ├── components/ui/        shadcn components
        ├── components/           shared: DataGrid (AG Grid wrapper), Chart, ProvenanceBadge, UnitToggle
        ├── features/             one folder per tab: statements/, ratios/, forecast/, valuation/, ...
        ├── lib/                  format.ts (scaling, parens), theme.ts, query-client.ts
        └── routes/               Login, Companies, Company/:ticker/:tab, Settings
```

## 4. Data Model

Conventions (apply to every table in every area):
- Monetary values are stored as `NUMERIC` (Python `Decimal`) in **units** (not scaled), with a `unit` column (`USD`, `shares`, `USD/shares`, `pure`). Scaling happens only in the UI. Engines convert to `float64` for statistics and convert back at the boundary.
- A period is identified by `(fiscal_year, fiscal_period ∈ {FY,Q1..Q4}, period_start, period_end)`. Instant (balance-sheet) items have `period_start = NULL`.
- Timestamps are UTC. Primary keys are integer surrogates, with natural unique constraints noted in each table definition.

Table definitions live in the area files:

| Tables | File |
|---|---|
| `company`, `filing`, `raw_fact`, `canonical_item`, `concept_mapping`, `adjustment`, `corporate_action`, `price_daily`, `shares_outstanding`, `macro_series` / `macro_observation`, `segment_value`, `unmapped_concept`; read paths (latest / `as_of`) | [erd/data.md](erd/data.md) |
| `comps_set` / `comps_member`, `guidance` | [erd/analysis.md](erd/analysis.md) |
| `note` | [erd/workspace.md](erd/workspace.md) |
| `scenario`, `driver_value`, `driver_engine_choice`, `forecast_run`, `forecast_value` | [erd/forecasting.md](erd/forecasting.md) |
| `valuation_run` | [erd/valuation.md](erd/valuation.md) |
| `backtest_result`, `audit_log` | [erd/accountability.md](erd/accountability.md) |

## 5. Data Flows

| Orig. § | Flow | File |
|---|---|---|
| 5.1 | Ingestion & statements (M1–M2), EDGAR specifics | [erd/data.md](erd/data.md) |
| 5.2 | Forecast & valuation (M4–M8) | [erd/forecasting.md](erd/forecasting.md) (sensitivity details also in [erd/valuation.md](erd/valuation.md)) |
| 5.3 | Accountability (M7) | [erd/accountability.md](erd/accountability.md) |

## 6. Core Interfaces

| Interface | File |
|---|---|
| `SeriesInput`, `ForecastResult`, `ForecastEngine`, `DriverModel` (Tier 1) + integrity rules, Tier 5 wrapper | [erd/forecasting.md](erd/forecasting.md) |
| `ValuationMethod` | [erd/valuation.md](erd/valuation.md) |
| `DataSource` | [erd/data.md](erd/data.md) |
| Ratio registry (`Ratio(...)`) | [erd/analysis.md](erd/analysis.md) |

## 7. API

Conventions (apply to every route):
- REST under `/api/v1`. Pydantic schemas are in `schemas/`, and every route declares a `response_model`.

Routes by area:

| Routes | File |
|---|---|
| `/auth/login`, `/auth/logout`, `/auth/me` | [erd/auth.md](erd/auth.md) |
| `/companies`, `/companies/{ticker}/refresh`, `/statements`, `/adjustments`; statement payload shape | [erd/data.md](erd/data.md) |
| `/ratios`, `/flags`, `/capital-allocation`, `/guidance` | [erd/analysis.md](erd/analysis.md) |
| `/health` (public) | [erd/platform.md](erd/platform.md) |
| `/notes`; API client codegen | [erd/workspace.md](erd/workspace.md) |
| `/scenarios`, `/scenarios/{id}/drivers`, `/scenarios/{id}/forecast` | [erd/forecasting.md](erd/forecasting.md) |
| `/forecast-runs/{id}/valuation` | [erd/valuation.md](erd/valuation.md) |
| `/forecast-runs/{id}/snapshot`, `/companies/{ticker}/backtest` | [erd/accountability.md](erd/accountability.md) |

## 8. Auth
See [erd/auth.md](erd/auth.md).

## 9. Configuration (env)
See [erd/platform.md](erd/platform.md#configuration-env-orig-9).

## 10. Testing Strategy
See [erd/platform.md](erd/platform.md#testing-strategy-orig-10).

## 11. CI & Deployment
See [erd/platform.md](erd/platform.md#ci--deployment-orig-11).

## 12. Coding Conventions
- Python: type hints everywhere; `mypy --strict` for all backend code (strict is a global mypy option, so it covers every package, not only the domain ones); Decimal at the storage boundary, float inside the statistics.
- As-reported data is append-only. User intent lives in `adjustment`, `concept_mapping` overrides, `driver_value` and `audit_log`.
- The frontend holds no financial logic. It only formats and displays; every calculation happens in the backend.
- Plug-ins (forecast engines, valuation methods, ratios) are added by registering in their registry; no switch statements across the codebase.
