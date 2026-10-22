"""Общие помощники роутеров: соединение psycopg (autocommit), выборка строк в словари, курсорная пагинация, доступ к сервисам приложения."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import dict_row

from app.db.session import psycopg_dsn


@asynccontextmanager
async def db() -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
    conn = await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True, row_factory=dict_row)
    try:
        yield conn
    finally:
        await conn.close()


async def fetch_all(
    conn: psycopg.AsyncConnection[dict[str, Any]], sql: str, args: tuple[Any, ...] | list[Any] = ()
) -> list[dict[str, Any]]:
    cur = await conn.execute(sql, args)
    return list(await cur.fetchall())


async def fetch_one(
    conn: psycopg.AsyncConnection[dict[str, Any]], sql: str, args: tuple[Any, ...] | list[Any] = ()
) -> dict[str, Any] | None:
    cur = await conn.execute(sql, args)
    return await cur.fetchone()


async def resolve_run_id(conn: psycopg.AsyncConnection[dict[str, Any]], run_id: str | None) -> int | None:
    """RunId из openapi: current (по умолчанию) | all | число."""
    if run_id in (None, "", "current"):
        row = await fetch_one(conn, "select current_run_id from sim_state where id = 1")
        return int(row["current_run_id"]) if row and row["current_run_id"] else None
    if run_id == "all":
        return None
    try:
        return int(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="run_id: current | all | integer") from exc


def page(items: list[dict[str, Any]], limit: int, key: str = "id") -> dict[str, Any]:
    return {"items": items, "next_cursor": str(items[-1][key]) if len(items) == limit and items else None}


def agent_service(request: Request) -> Any:
    svc = getattr(request.app.state, "agent", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="агент не запущен (APP_ENV=test?)")
    return svc
