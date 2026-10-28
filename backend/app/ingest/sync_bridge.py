"""Синхронный seed использует тот же normalizer, сохраняя одну внешнюю транзакцию.

Адаптер реализует используемую SQL-часть async-протокола поверх текущего sync-соединения.
Он не открывает вторую БД и не делает commit: ошибка откатывает весь seed истории.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import psycopg
from psycopg.pq import TransactionStatus

from app.ingest.normalizer import create_signal


class _Cursor:
    def __init__(self, cursor: psycopg.Cursor[Any]) -> None:
        self.cursor = cursor

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        self.cursor.execute(sql, args)

    async def fetchone(self) -> Any:
        return self.cursor.fetchone()

    async def fetchall(self) -> list[Any]:
        return self.cursor.fetchall()


class _Connection:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _Cursor:
        return _Cursor(self.conn.execute(sql, args))

    @asynccontextmanager
    async def cursor(self, **kwargs: Any) -> AsyncIterator[_Cursor]:
        with self.conn.cursor(**kwargs) as cur:
            yield _Cursor(cur)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        with self.conn.transaction():
            yield


def create_signal_sync(
    conn: psycopg.Connection[Any], msg: dict[str, Any], *, run_id: int, sim_time: dt.datetime
) -> dict[str, Any]:
    if conn.autocommit:
        raise ValueError("seed normalizer требует соединение без autocommit")
    if conn.info.transaction_status == TransactionStatus.IDLE:
        conn.execute("select 1")  # Открываем внешнюю транзакцию; normalizer использует только SAVEPOINT.
    return asyncio.run(
        create_signal(
            cast(Any, _Connection(conn)), msg, source_code="csi", run_id=run_id, sim_time=sim_time, emit_event=False
        )
    )


def reconcile_seed_sync(conn: psycopg.Connection[Any], *, run_id: int) -> int:
    from app.ingest.csi import reconcile_seed_rows

    if conn.autocommit:
        raise ValueError("seed normalizer требует соединение без autocommit")
    if conn.info.transaction_status == TransactionStatus.IDLE:
        conn.execute("select 1")
    return asyncio.run(reconcile_seed_rows(cast(Any, _Connection(conn)), run_id=run_id))
