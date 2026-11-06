# Build context: the repo root (`docker build -f backend/Dockerfile .`).

# --- web: build the SPA ---
FROM node:24-alpine AS web
WORKDIR /app/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# --- app: production image ---
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# The venv lives outside /app/backend so the dev profile can bind-mount the source over it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /app/frontend/dist /app/static
ENV STATIC_DIR=/app/static \
    DATA_DIR=/data
EXPOSE 8000
# 3 workers: a tab's parallel requests are CPU-bound (statement builds), so one process would
# serialize them on the GIL (NFR-02; erd/platform.md "Docker").
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn bedrock.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 3"]

# --- dev: app + dev deps, auto-reload (source is bind-mounted by compose) ---
FROM app AS dev
RUN uv sync --frozen
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn bedrock.main:create_app --factory --host 0.0.0.0 --port 8000 --reload"]
