"""Межпроцессный lease для cooperating personal HTTP/seed и baseline restore."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import psycopg
from starlette.types import ASGIApp, Receive, Scope, Send

from app.db.session import psycopg_dsn
from app.errors import Problem
from app.sim.maintenance import MaintenanceBusy
from app.sim.maintenance_control import ControlError, MaintenanceControl

# Двухключевой namespace проекта, не совпадает с CSI/HITL/personal locks.
LOCK = (40, 0)


class DatabaseBoundary:
    """Exclusive connection переживает failed restore до явного успешного retry."""

    def __init__(self, *, dsn: str | None = None, timeout_ms: int = 30_000) -> None:
        self.dsn, self.timeout_ms = dsn, timeout_ms
        self.conn: psycopg.AsyncConnection[Any] | None = None

    async def acquire(self) -> None:
        if self.conn is not None and not self.conn.closed:
            return
        conn = await psycopg.AsyncConnection.connect(psycopg_dsn(self.dsn), autocommit=True, connect_timeout=3)
        try:
            await conn.execute("select set_config('lock_timeout',%s,false)", (f"{self.timeout_ms}ms",))
            await conn.execute("select pg_advisory_lock(%s,%s)", LOCK)
        except BaseException as exc:
            await conn.close()
            if isinstance(exc, psycopg.errors.LockNotAvailable):
                raise MaintenanceBusy("Public HTTP/CLI seed ещё активен; восстановление не начато") from None
            raise
        self.conn = conn

    async def release(self) -> None:
        conn = self.conn
        if conn is not None:
            await conn.close()
            self.conn = None
        # Session advisory lock освобождается только здесь.


@contextlib.asynccontextmanager
async def public_operation(dsn: str | None = None) -> AsyncIterator[None]:
    try:
        MaintenanceControl().require_idle()
    except ControlError as exc:
        raise MaintenanceBusy(str(exc)) from None
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(dsn), autocommit=True, connect_timeout=3) as conn:
        row = await (await conn.execute("select pg_try_advisory_lock_shared(%s,%s)", LOCK)).fetchone()
        if not row or not row[0]:
            raise MaintenanceBusy("Baseline в режиме обслуживания; повторите запрос после завершения")
        try:
            MaintenanceControl().require_idle()
        except ControlError as exc:
            raise MaintenanceBusy(str(exc)) from None
        # Одна отдельная session живёт до ASGI cleanup/commit, не до ответа headers.
        yield


class PublicMaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        try:
            async with public_operation():
                await self.app(scope, receive, send)
        except MaintenanceBusy as exc:
            await Problem(503, "Baseline в режиме обслуживания", exc.detail).to_response(scope["path"])(
                scope, receive, send
            )
