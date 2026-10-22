FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY contracts/ /contracts/
COPY data/ /data/
COPY scripts/ /scripts/
RUN uv sync --frozen --no-dev
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=12 CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
