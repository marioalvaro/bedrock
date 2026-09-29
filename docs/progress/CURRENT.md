# M0 — Scaffold · Progress

> Source: [PRD.md §8](../PRD.md#8-milestone-roadmap) · Status: `in-progress` · Planned: 2026-09-27
> Areas: [prd/auth.md](../prd/auth.md) + [erd/auth.md](../erd/auth.md) · [prd/workspace.md](../prd/workspace.md) + [erd/workspace.md](../erd/workspace.md) · [erd/platform.md](../erd/platform.md) · stack/structure [ERD.md §2–§3](../ERD.md#2-tech-stack)

**Scope**: monorepo, backend and frontend skeletons, Docker Compose, CI, FR-AUTH-01, FR-AUTH-02, and an empty shell UI with a theme toggle.
**Acceptance** (roadmap): `docker compose up` serves a login page; after login, an empty company list; CI green.

## Prerequisites
- [x] `uv` installed (`brew install uv`). It installs Python 3.12 itself; the system Python is 3.10.
- [ ] Docker Desktop running (Docker 28 / Compose v2 detected).
- [ ] Node 24 + pnpm 10 (detected: node v24.11.0, pnpm 10.8.1).
- [ ] Push access to `origin` (github.com/marioalvaro/bedrock) so CI can run. `gh` is not installed, so CI status is checked on the GitHub web UI.

## Steps
| # | Step | Requirements | Depends on | Status |
|---|---|---|---|---|
| S1 | Backend foundation: uv project, settings, DB + Alembic, `company` table, health + company list API, CLI | — (M0 scaffold) | — | `done` |
| S2 | Auth: password login, session cookie, idle timeout, throttle, route guard | FR-AUTH-01, FR-AUTH-02 | S1 | `todo` |
| S3 | Frontend shell: Vite/React/TS, Tailwind + shadcn, theme toggle, router, generated API client, login + empty company list | FR-AUTH-01, FR-AUTH-02 | S2 | `todo` |
| S4 | Docker Compose (dev + prod), SPA serving from backend, `.env.example`, GitHub Actions CI | — (M0 scaffold) | S3 | `todo` |

---

## S1 — Backend foundation
**Goal**: an installable, typed, tested FastAPI backend with SQLite + Alembic, serving a health check and an (empty) company list.

**Read**: [ERD.md §1–§4, §7, §12](../ERD.md); the `company` row in [erd/data.md](../erd/data.md#tables-orig-4); [erd/platform.md](../erd/platform.md).

**Build**:
- `backend/pyproject.toml`:
  - uv project, `requires-python = ">=3.12,<3.13"`, `.python-version` = `3.12`, `hatchling` build backend, src layout `backend/src/bedrock/`.
  - Deps: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy>=2`, `alembic`, `typer`, `argon2-cffi`, `itsdangerous`.
  - Dev group: `pytest`, `httpx`, `ruff`, `mypy`.
  - Script: `bedrock = "bedrock.cli:app"`.
- Tool config in `pyproject.toml`:
  - ruff: `line-length = 100`, lint `select = ["E","F","I","UP","B"]`.
  - mypy: `strict = true`, `plugins = ["pydantic.mypy"]`.
  - pytest: `testpaths = ["tests"]`.
- `bedrock/core/config.py`: a `Settings` class (pydantic-settings), reading env files `(".env", "../.env")`. Fields:
  - `data_dir: Path = Path("../data")`
  - `database_url: str | None = None`, which resolves to `sqlite:///{data_dir}/bedrock.db` when unset
  - `sec_user_agent: str | None = None`
  - `fred_api_key: str | None = None`
  - `app_password_hash: str = ""`
  - `session_secret: str = "dev-insecure-change-me"`
  - `session_idle_minutes: int = 720`
  - `cookie_secure: bool = False`
  - `static_dir: Path | None = None`

  Expose it via `get_settings()`, cached with `lru_cache`.
- `bedrock/core/db.py`:
  - `make_engine(url)`, which creates `data_dir` if missing and, for SQLite, sets `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` on connect;
  - a `sessionmaker`;
  - a FastAPI dependency `get_session()`.
- `bedrock/models/base.py`: `DeclarativeBase` with a constraint naming convention.
- `bedrock/models/company.py`: `Company` with the exact columns from erd/data.md (`id`, `ticker` uq, `cik` uq, `name`, `fiscal_year_end_month`, `currency`, `sic`, `last_refreshed_at`). Nullable: `sic`, `last_refreshed_at`.
- Alembic in `backend/migrations/` with `backend/alembic.ini`:
  - `env.py` takes its URL from `get_settings()` and uses `Base.metadata` with `render_as_batch=True`.
  - The first revision creates `company`.
- `bedrock/schemas/company.py`: `CompanyOut` (all columns).
- `bedrock/api/v1/`:
  - `health.py`: `GET /api/v1/health` → `{"status": "ok"}`.
  - `companies.py`: `GET /api/v1/companies` → `list[CompanyOut]`, ordered by ticker. Uses `response_model`, and goes through a thin `services/companies.py::list_companies(session)`.
- `bedrock/main.py`: `create_app(settings: Settings | None = None) -> FastAPI` factory that includes the v1 routers.
- `bedrock/cli.py`: Typer `app` with:
  - `hash-password`: prompts twice, hidden input, and prints the argon2 hash;
  - `export-openapi PATH`: writes `create_app().openapi()` as pretty JSON with sorted keys. Used by S3 and S4.
- `backend/tests/conftest.py`: sets env for a temp `data_dir`, builds the app with `create_app`, creates the schema via `Base.metadata.create_all`, and provides a `client` fixture (`TestClient`).
- Tests:
  - health returns 200;
  - companies returns `[]`, and a seeded row is returned with correct fields;
  - `alembic upgrade head` on a fresh temp DB creates the `company` table;
  - `hash-password` output verifies with `argon2.PasswordHasher().verify`;
  - `export-openapi` writes valid JSON containing `/api/v1/companies`.

**Verify** (from `backend/`):
- `uv sync` → exit 0
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src` → exit 0
- `uv run pytest` → all pass
- `uv run alembic upgrade head` → creates `../data/bedrock.db` with a `company` table
- `uv run uvicorn bedrock.main:create_app --factory --port 8000`, then `curl -s localhost:8000/api/v1/health` → `{"status":"ok"}`

**Done when**: every Verify line passes.
**Log**: 2026-09-27 — Built as specced: uv project (`backend/pyproject.toml`, `.python-version`), `Settings`/`get_settings`, `db.py` (`make_engine`/`make_sessionmaker`/`build_get_session`/`get_session`), `Company` model + Alembic migration `0001`, `CompanyOut`, `services/companies.py::list_companies`, `/api/v1/health` + `/api/v1/companies`, `create_app` factory, `cli.py` (`hash-password`, `export-openapi`), `conftest.py` + 6 tests (health, companies empty/seeded, alembic upgrade, hash-password verify, export-openapi). All Verify lines pass: `uv sync`, `ruff check`/`ruff format --check`, `mypy src` (strict, 17 files), `pytest` (6 passed), `alembic upgrade head` (creates `../data/bedrock.db` with `company`), live uvicorn `curl` on `/api/v1/health` and `/api/v1/companies`.
Deviations: `create_app(settings=...)` is wired via `app.dependency_overrides` on `get_session` (not left as a dead parameter) so tests inject an isolated `Settings`/temp DB per test rather than relying on the global `lru_cache`d `get_settings()` singleton — kept per-request engine creation (no cross-test engine caching) for isolation correctness. Added `[tool.ruff.lint.per-file-ignores]` for `B008` on `src/bedrock/api/**` (FastAPI's `Depends(...)` default-arg pattern is a known ruff false positive). Added `alembic.ini`'s `path_separator = os` to silence a deprecation warning. Extended root `.gitignore` with backend build artifacts (`backend/.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`) generated by this step; full artifact list (`frontend/node_modules` etc.) still lands in S4.

---

## S2 — Auth
**Goal**: single-user login protects every API route except login and health (FR-AUTH-01), with logout and idle expiry (FR-AUTH-02).

**Read**: [prd/auth.md](../prd/auth.md), [erd/auth.md](../erd/auth.md).

**Build**:
- `bedrock/core/auth.py`:
  - `verify_password(plain) -> bool`: argon2 check against `settings.app_password_hash`; an empty hash always fails.
  - `LoginThrottle`, in-memory and keyed by client IP: after 5 failures within 15 min, further attempts get 429 until 15 min after the last failure. A success resets the count. It is injectable, so tests can control time.
  - `require_session` dependency:
    - The session must hold `auth=True`.
    - If `now - last_seen > session_idle_minutes`, clear the session and return 401.
    - Otherwise refresh `last_seen` and continue.
- Add `SessionMiddleware` in `create_app`: `secret_key=settings.session_secret`, `session_cookie="bedrock_session"`, `same_site="lax"`, `https_only=settings.cookie_secure`.
- `bedrock/api/v1/auth.py`:
  - `POST /api/v1/auth/login`, body `{"password": str}` → 204 and sets the session (`auth=True`, `last_seen=now`); 401 on a wrong password; 429 when throttled.
  - `POST /api/v1/auth/logout` → 204, clears the session.
  - `GET /api/v1/auth/me` → 200 `{"authenticated": true}` behind `require_session`; otherwise 401.
- Guard: every v1 router except `auth/login` and `health` is mounted with `dependencies=[Depends(require_session)]`. `companies` becomes protected.
- `conftest.py`:
  - test password `test-password`, with its hash put in the env;
  - an `authed_client` fixture that logs in.
- Tests:
  - correct password → 204 plus cookie;
  - wrong password → 401;
  - 6th attempt after 5 failures → 429;
  - `companies` without a session → 401; with a session → 200;
  - logout, then `me` → 401;
  - idle expiry: advance the clock past `session_idle_minutes`, then `me` → 401;
  - `health` is public.

**Verify** (from `backend/`):
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` → exit 0
- Manual, with `.env` holding `APP_PASSWORD_HASH` from `uv run bedrock hash-password`, and uvicorn running:
  - `curl -i localhost:8000/api/v1/companies` → 401
  - `curl -i -c /tmp/j -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' -d '{"password":"<pw>"}'` → 204
  - `curl -s -b /tmp/j localhost:8000/api/v1/companies` → `[]`

**Done when**: every Verify line passes, and the S1 tests still pass.
**Log**: _(implementer fills in)_

---

## S3 — Frontend shell
**Goal**: a flat, dense, TradingView-like SPA shell with login, route guard, dark/light theme toggle and an empty company list, all driven by the generated API client.

**Read**: [prd/workspace.md](../prd/workspace.md) (design principles, page map); [erd/workspace.md](../erd/workspace.md); [ERD.md §2–§3](../ERD.md#2-tech-stack) (frontend rows and tree).

**Build**:
- Scaffold `frontend/` with `pnpm create vite frontend --template react-ts`. TypeScript `strict: true`. Keep the template's ESLint flat config; add Prettier (`printWidth: 100`) and a `format` script.
- Styling:
  - Tailwind CSS v4 via `@tailwindcss/vite`.
  - shadcn/ui init (style `new-york`, base color `neutral`, CSS variables on); add components `button`, `input`, `label`.
  - Design tokens in `src/index.css`: CSS variables for light and `.dark`, `--radius: 0.25rem`, no shadows, hairline `border` color. Body font system UI at 13px; a `.num` utility with `font-variant-numeric: tabular-nums` and right alignment.
- Theme in `src/lib/theme.ts`:
  - `getInitialTheme()`: `localStorage["theme"]`, else `prefers-color-scheme`;
  - `applyTheme(t)`: toggles the `dark` class on `<html>` and persists the choice;
  - `ThemeToggle` component in the header.
- API client:
  - backend `uv run bedrock export-openapi ../frontend/openapi.json`, with the output committed;
  - `@hey-api/openapi-ts` + `@hey-api/client-fetch`;
  - `pnpm gen:api` = `openapi-ts -i openapi.json -o src/api/generated -c @hey-api/client-fetch`;
  - generated output is committed and never hand-edited;
  - base URL `""` (same origin), `credentials: "include"`.
- Data and routing:
  - TanStack Query v5 in `src/lib/query-client.ts`;
  - `react-router` v7 in library mode.
- Routes (`src/routes/`):
  - `/login`: password form → login → navigate to `/`; the error text distinguishes 401 from 429.
  - `/`: Companies list via `useQuery` on the list endpoint. Empty state: "No companies yet. Adding companies arrives in M1."
  - `/c/:ticker/:tab?`: placeholder with the tab bar from the page map (only Overview shown).
  - `/settings`: placeholder containing the theme toggle.
  - `RequireAuth` wraps everything except `/login`: it calls `auth/me`, and on 401 redirects to `/login`.
  - Header: app name "Bedrock", nav (Companies, Settings), theme toggle, logout (calls logout, then goes to `/login`).
- `vite.config.ts`: dev proxy `/api` → `process.env.VITE_API_TARGET ?? "http://localhost:8000"`.
- Tests (Vitest + `@testing-library/react` + `jsdom`):
  - `theme.ts`: stored value wins; falls back to the media query; `applyTheme` toggles the class and persists.
  - `RequireAuth`: mocked 401 → redirects to `/login`; mocked 200 → renders children.
- Scripts: `lint`, `typecheck` (`tsc -b --noEmit`), `test` (`vitest run`), `build`, `gen:api`, `format`.

**Verify** (from `frontend/`):
- `pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build` → exit 0
- `pnpm gen:api && git diff --exit-code src/api/generated` → no diff
- Manual, with the backend running (S2) and `pnpm dev`, at http://localhost:5173:
  - redirected to `/login`;
  - wrong password shows an error;
  - correct password shows the empty company list;
  - the theme toggle switches dark/light and survives a reload;
  - logout returns to `/login`;
  - at 375px width, no horizontal page scroll.

**Done when**: every Verify line passes, and the backend tests still pass.
**Log**: _(implementer fills in)_

---

## S4 — Docker Compose & CI
**Goal**: one command runs the app (prod profile, backend serving the built SPA) or the dev setup, and GitHub Actions gates every push.

**Read**: [erd/platform.md](../erd/platform.md).

**Build**:
- Backend SPA serving: when `settings.static_dir` is set, `create_app`
  - mounts `static_dir/assets` at `/assets`, and
  - serves `static_dir/index.html` for any non-`/api` GET path (the SPA fallback).
  - Test: with a temp `static_dir`, `GET /` and `GET /c/AAPL` return the index HTML, and `/api/v1/health` is still JSON.
- `backend/Dockerfile`, with the repo root as build context:
  - stage `web`: `node:24-alpine`, `corepack enable`, `pnpm install --frozen-lockfile`, `pnpm build`.
  - stage `app`: `python:3.12-slim`, uv copied from `ghcr.io/astral-sh/uv:latest`, `uv sync --frozen --no-dev`; copies `frontend/dist` to `/app/static`; env `STATIC_DIR=/app/static`, `DATA_DIR=/data`; `EXPOSE 8000`; CMD runs `alembic upgrade head`, then `uvicorn bedrock.main:create_app --factory --host 0.0.0.0 --port 8000`.
  - stage `dev`: from `app`, with the dev deps installed.
- `frontend/Dockerfile.dev`: `node:24-alpine`, `corepack enable`, `pnpm install`, CMD `pnpm dev --host 0.0.0.0`.
- `docker-compose.yml`:
  - profile `prod`: service `app` (target `app`), `ports: 8000:8000`, `env_file: .env`, volume `./data:/data`.
  - profile `dev`:
    - service `backend` (target `dev`): source mounted at `./backend`, `uvicorn --reload`, port 8000, `env_file: .env`, volume `./data:/data`;
    - service `web` (`frontend/Dockerfile.dev`): source mounted with an anonymous `node_modules` volume, `VITE_API_TARGET=http://backend:8000`, port 5173.
- `.env.example`: every variable in erd/platform.md, including `STATIC_DIR` and `COOKIE_SECURE`, each with a comment. `.gitignore` already covers `.env` and `data/`; add `frontend/node_modules`, `frontend/dist`, `backend/.venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`.
- `.github/workflows/ci.yml`, on push and pull_request, with jobs:
  - `backend`: `astral-sh/setup-uv`, then `uv sync`, `ruff check`, `ruff format --check`, `mypy src`, `pytest` (working-directory `backend`);
  - `frontend`: `pnpm/action-setup`, `actions/setup-node` (node 24, pnpm cache), `pnpm install --frozen-lockfile`, `lint`, `typecheck`, `test`, `build`;
  - `api-drift`: `uv run bedrock export-openapi ../frontend/openapi.json`, then `pnpm gen:api`, then `git diff --exit-code frontend/openapi.json frontend/src/api/generated`;
  - `docker`: `docker build -f backend/Dockerfile --target app .`

**Verify**:
- backend and frontend suites still pass (commands from S1–S3)
- `cp .env.example .env`, then set `APP_PASSWORD_HASH` and `SESSION_SECRET`
- `docker compose --profile prod up --build -d`, then:
  - `curl -s localhost:8000/api/v1/health` → `{"status":"ok"}`
  - `curl -s localhost:8000/ | grep -q '<div id="root">'` → exit 0
  - browser at http://localhost:8000 → login → empty company list
  - `docker compose --profile prod down`
- `docker compose --profile dev up --build` → http://localhost:5173 works, and editing a backend file reloads uvicorn
- Push the branch → all 4 CI jobs green on GitHub

**Done when**: every Verify line passes.
**Log**: _(implementer fills in)_

---

## Milestone acceptance
- [ ] `docker compose --profile prod up --build` serves the login page at http://localhost:8000
- [ ] After login, the company list shows its empty state
- [ ] Theme toggle switches dark/light and persists
- [ ] Logout works, and sessions expire after `SESSION_IDLE_MINUTES` (covered by the S2 tests)
- [ ] CI green on GitHub (all 4 jobs)
