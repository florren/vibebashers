FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /tgbot
COPY tgbot/pyproject.toml tgbot/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY tgbot/cx_tgbot ./cx_tgbot
RUN uv sync --frozen --no-dev --no-editable
USER 65532:65532
CMD ["python", "-m", "cx_tgbot.main"]
