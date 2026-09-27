# ERD · Platform (Config, Testing, CI & Deployment)

> Split of [ERD.md](../ERD.md), originally §9 (Configuration), §10 (Testing Strategy) and §11 (CI & Deployment).
> Product counterpart: NFR-04 to NFR-06 in [PRD.md §7](../PRD.md#7-non-functional-requirements); milestones M0 (scaffold) and M9 (deploy).

## Configuration (env) (orig. §9)
| Var | Purpose |
|---|---|
| `DATABASE_URL` | default `sqlite:///data/bedrock.db` |
| `DATA_DIR` | raw JSON cache, DB file (Docker volume) |
| `SEC_USER_AGENT` | required by SEC, e.g. `Bedrock you@example.com` |
| `FRED_API_KEY` | M8 |
| `APP_PASSWORD_HASH`, `SESSION_SECRET`, `SESSION_IDLE_MINUTES` | auth |
| `COOKIE_SECURE` | set the session cookie `Secure` flag (true behind HTTPS) |
| `STATIC_DIR` | built SPA directory; when set, the backend serves it with an `index.html` fallback for non-`/api` paths (prod) |

Settings are loaded via `pydantic-settings` from `.env` (git-ignored), with a committed `.env.example`.

## Testing Strategy (orig. §10)
- **TDD** for domain engines (mapping, statements, ratios, analysis, forecast, valuation, backtest): write a failing test first.
- **No network in tests.** EDGAR/yfinance/FRED adapters are tested against recorded fixtures in `tests/fixtures/`. A separate, opt-in `-m live` marker runs smoke tests against the real APIs.
- **Golden tests**: expected statement lines and ratios for AAPL, MSFT, COST and DE for selected years, checked by hand against 10-Ks, stored in `tests/golden/`.
- **Invariant tests**: A = L + E on history (within tolerance) and on every forecast; cash and RE roll-forwards; Q1+Q2+Q3+Q4 = FY for flows.
- **API tests**: FastAPI `TestClient` against a temporary SQLite database.
- **Frontend**: Vitest for `lib/format.ts` and similar pure logic; no E2E suite in v1.

## CI & Deployment (orig. §11)
- **CI** (GitHub Actions, on push/PR):
  - backend: `uv sync` → `ruff check` → `ruff format --check` → `mypy` → `pytest`
  - frontend: `pnpm install` → `lint` → `tsc --noEmit` → `vitest` → `build`
  - API client drift check (export OpenAPI → regenerate client → `git diff --exit-code`)
  - Docker image build
- **Docker Compose**:
  - `dev` profile: backend with reload + Vite dev server, which proxies `/api` to the backend.
  - `prod` profile: a single backend container serves the built SPA as static files, with a volume for `DATA_DIR`.
- **Images**: one multi-stage `backend/Dockerfile` (build context = repo root). Stage `web` builds the SPA, stage `app` is the prod image (runs `alembic upgrade head`, then uvicorn), and stage `dev` adds the dev deps. The frontend dev server uses `frontend/Dockerfile.dev`.
- **Health**: public `GET /api/v1/health` → `{"status": "ok"}`.
- **Deploy path**: laptop (M0–M8) → home server with the `prod` profile, reached over Tailscale; HTTPS via `tailscale serve` (M9).
- **Backups**: SQLite `.backup` of the DB file via a CLI command (`bedrock backup`).
