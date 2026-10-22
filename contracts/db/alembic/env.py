"""Alembic env для CX Pulse Control.

Правила (см. AGENTS.md):
- URL БД только из переменной окружения DATABASE_URL (формат postgresql+psycopg://…).
- Автогенерация сравнивает с metadata SQLAlchemy-моделей backend/app/db/models.py; первая миграция
  0001 исполняет contracts/db/schema.sql целиком — модели обязаны соответствовать ему.
- Миграции идемпотентны по возможности (IF NOT EXISTS) и не трогают данные без явного ADR.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

try:  # metadata моделей появляется в эпике E1; до этого автогенерация недоступна, ручные миграции работают
    from app.db.models import Base  # type: ignore

    target_metadata = Base.metadata
except Exception:  # pragma: no cover
    target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
