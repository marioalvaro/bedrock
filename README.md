# Bedrock

A personal web app for deep fundamental analysis of a handful of US companies, similar to TradingView's "Fundamentals" tab but with no price charts. Data comes from SEC EDGAR. On top of the raw statements it adds a forecasting and valuation layer that keeps the three statements accounting-consistent and scores past forecasts against actuals.

It is a single-user app: a FastAPI + SQLite backend and a React (Vite, TypeScript, Tailwind) SPA, in one repo.

> **Status:** milestone M0 (scaffold) is in progress. It includes login, an empty company list, Docker and CI. Financial data arrives from M1.

## API

Every route is under `/api/v1`. Interactive docs are at `/docs` on a running backend.

| Method | Path | Auth | Response |
|---|---|---|---|
| `GET` | `/health` | public | `{"status": "ok"}` |
| `POST` | `/auth/login` | public | Body `{"password": "..."}`. Returns `204` and sets the `bedrock_session` cookie, or `401` for a wrong password, or `429` after 5 failures in 15 min. |
| `POST` | `/auth/logout` | public | `204` and clears the session |
| `GET` | `/auth/me` | session | `{"authenticated": true}`, or `401` |
| `GET` | `/companies` | session | The list of followed companies |

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

## Tests and checks

These are the same commands CI runs (`.github/workflows/ci.yml`).

```sh
# backend
cd backend
uv run pytest            # unit and API tests: in-process TestClient, temporary SQLite, no network
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

Backend code is written test-first. The backend tests don't depend on your environment or `.env`: the test settings pin every value.

## License

MIT. See [LICENSE](LICENSE).
