# Сборка фронта (frontend/dist) → копируется в образ backend; FastAPI раздаёт SPA с того же порта 8000 (app.main.mount_frontend).
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" FRONTEND_DIST=/frontend/dist
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY contracts/ /contracts/
COPY data/ /data/
COPY scripts/ /scripts/
COPY --from=frontend /fe/dist /frontend/dist
RUN uv sync --frozen --no-dev
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=12 CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
