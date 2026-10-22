"""Подключение к PostgreSQL: async engine (psycopg3), фабрика сессий, зависимость FastAPI, соединение для LISTEN."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

import psycopg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    return create_async_engine(s.database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def psycopg_dsn(url: str | None = None) -> str:
    """postgresql+psycopg://… → postgresql://… для «сырого» psycopg (LISTEN/NOTIFY, COPY)."""
    return (url or get_settings().database_url).replace("postgresql+psycopg://", "postgresql://", 1)


async def listen_connection(channels: list[str]) -> psycopg.AsyncConnection[object]:
    """Отдельное autocommit-соединение, подписанное на каналы pg_notify (AGENTS.md §3 app/realtime)."""
    conn = await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True)
    for ch in channels:
        await conn.execute(f"LISTEN {ch}")
    return conn
