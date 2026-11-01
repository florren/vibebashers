"""T-040: process-wide admission/drain логических операций ASGI runtime."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, ParamSpec, Protocol, TypeVar

from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import Problem
from app.logging import get_logger
from app.sim.maintenance_control import ControlError, MaintenanceControl

log = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")
_BOUND: ContextVar[MaintenanceCoordinator | None] = ContextVar("maintenance", default=None)
PROTECTED = frozenset({"audio", "seed"})


class MaintenanceBusy(Problem):
    def __init__(self, detail: str = "Дождитесь завершения активных операций перед восстановлением") -> None:
        super().__init__(409, "Baseline сейчас недоступен", detail)


@dataclass
class Operation:
    kind: str
    epoch: int


async def completion[R](task: asyncio.Task[R], *, propagate_cancel: bool) -> R:
    """Ожидающий не отменяет supervised writer/psql и всегда забирает результат."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    if cancelled and propagate_cancel:
        with contextlib.suppress(BaseException):
            task.result()
        raise asyncio.CancelledError
    return task.result()


class RestoreBoundary(Protocol):
    async def acquire(self) -> None: ...
    async def release(self) -> None: ...


class MaintenanceCoordinator:
    def __init__(
        self,
        *,
        drain_timeout: float = 30,
        boundary: RestoreBoundary | None = None,
        control: MaintenanceControl | None = None,
    ) -> None:
        self.boundary = boundary
        self.control = control
        self.drain_timeout = drain_timeout
        self.phase = "ready"
        self.epoch = 0
        self.job_id: str | None = None
        self.failure: str | None = None
        self._records: dict[asyncio.Task[Any], Operation] = {}
        self._changed = asyncio.Event()
        self._ready = asyncio.Event()
        self._ready.set()
        self._job: asyncio.Task[str] | None = None
        self._owner: asyncio.Task[Any] | None = None

    @contextlib.contextmanager
    def bind(self) -> Iterator[None]:
        token = _BOUND.set(self)
        try:
            yield
        finally:
            _BOUND.reset(token)

    @contextlib.asynccontextmanager
    async def operation(self, kind: str, *, recovery: bool = False) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Операция требует asyncio Task")
        if task is self._owner:
            yield
            return
        existing = self._records.get(task)
        if existing is not None:
            if existing.epoch != self.epoch:
                raise MaintenanceBusy("Операция относится к старому состоянию")
            yield
            return
        if self.phase != "ready" and not (recovery and self.phase == "failed"):
            raise MaintenanceBusy()
        self._records[task] = Operation(kind, self.epoch)
        self._changed.set()
        try:
            with self.bind():
                yield
        finally:
            self._records.pop(task, None)
            self._changed.set()

    def spawn(self, coro: Coroutine[Any, Any, R], *, kind: str, name: str | None = None) -> asyncio.Task[R]:
        parent_task = asyncio.current_task()
        parent = self._records.get(parent_task) if parent_task is not None else None
        if self.phase != "ready" and not (parent is not None and parent.epoch == self.epoch):
            coro.close()
            raise MaintenanceBusy()
        started = False
        epoch = self.epoch

        async def run() -> R:
            nonlocal started
            started = True
            if epoch != self.epoch:
                coro.close()
                raise MaintenanceBusy("Фоновая задача относится к старому состоянию")
            with self.bind():
                return await coro

        task = asyncio.create_task(run(), name=name)
        # Child регистрируется до первого шага, даже если HTTP уже завершится.
        self._records[task] = Operation(kind, epoch)
        self._changed.set()

        def done(finished: asyncio.Task[R]) -> None:
            if not started:
                coro.close()
            self._records.pop(finished, None)
            self._changed.set()

        task.add_done_callback(done)
        return task

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def _drain(self, initiator: asyncio.Task[Any] | None) -> None:
        deadline = asyncio.get_running_loop().time() + self.drain_timeout
        while True:
            self._changed.clear()
            active = {task: row for task, row in self._records.items() if task is not initiator}
            if any(row.kind in PROTECTED for row in active.values()):
                raise MaintenanceBusy("Остановите аудио или дождитесь завершения генерации данных")
            if not active:
                return
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise MaintenanceBusy("Активные операции не завершены; восстановление не начато")
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError as exc:
                raise MaintenanceBusy("Активные операции не завершены; восстановление не начато") from exc

    async def restore(
        self,
        action: Callable[[str], Awaitable[str]],
        *,
        preflight: Callable[[], Awaitable[None]] | None = None,
        park: Callable[[], Awaitable[None]] | None = None,
        resume: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        if self.phase not in {"ready", "failed"} or (self._job is not None and not self._job.done()):
            raise MaintenanceBusy("Другой job восстановления ещё выполняется")
        if any(row.kind in PROTECTED for row in self._records.values()):
            raise MaintenanceBusy("Остановите аудио или дождитесь завершения генерации данных")
        previous = self.phase
        initiator = asyncio.current_task()
        self.job_id = str(uuid.uuid4())
        job_id = self.job_id
        self.phase = "draining"
        self._ready.clear()
        self._changed.set()

        async def supervised() -> str:
            effects = False
            self._owner = asyncio.current_task()
            try:
                with self.bind():
                    if self.control is not None:
                        self.control.write("draining", job_id)
                    await self._drain(initiator)
                    if self.boundary is not None:
                        await self.boundary.acquire()
                    if preflight is not None:
                        await preflight()
                    effects = True
                    if self.control is not None:
                        self.control.write("restoring", job_id)
                    if park is not None:
                        await park()
                    self.phase = "restoring"
                    self._changed.set()
                    result = await action(job_id)
                    self.phase = "reloading"
                    if self.control is not None:
                        self.control.write("reloading", job_id)
                    if resume is not None:
                        await resume()
                    self.epoch += 1
                    if initiator is not None and initiator in self._records:
                        self._records[initiator].epoch = self.epoch
                    if self.boundary is not None:
                        await self.boundary.release()
                    if self.control is not None:
                        self.control.write("idle")
                    self.failure = None
                    self.phase = "ready"
                    self._ready.set()
                    self._changed.set()
                    return result
            except BaseException as exc:
                self.failure = type(exc).__name__
                self.phase = "failed" if effects else previous
                if not effects and self.boundary is not None:
                    try:
                        await self.boundary.release()
                    except BaseException:
                        self.phase = "failed"
                        self._changed.set()
                        raise
                if self.control is not None:
                    try:
                        self.control.write(
                            "idle" if self.phase == "ready" else "failed", None if self.phase == "ready" else job_id
                        )
                    except ControlError:
                        self.phase = "failed"
                        log.error("baseline_maintenance_control_failed", job_id=job_id)
                log.warning("baseline_maintenance_failed", error_type=self.failure, phase=self.phase, job_id=job_id)
                if self.phase == "ready":
                    self._ready.set()
                self._changed.set()
                raise
            finally:
                self._owner = None

        self._job = asyncio.create_task(supervised(), name="baseline-restore")
        return await completion(self._job, propagate_cancel=True)

    async def join_restore(self) -> None:
        if self._job is not None:
            await completion(self._job, propagate_cancel=False)


def current() -> MaintenanceCoordinator | None:
    return _BOUND.get()


@contextlib.asynccontextmanager
async def writer_lease(kind: str) -> AsyncIterator[None]:
    coordinator = _BOUND.get()
    if coordinator is None:
        yield  # CLI/tests вне ASGI не являются запущенным runtime.
    else:
        async with coordinator.operation(kind):
            yield


def writer(kind: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]]:
    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            async with writer_lease(kind):
                return await fn(*args, **kwargs)

        return wrapped

    return decorate


def spawn_writer[R](coro: Coroutine[Any, Any, R], *, kind: str, name: str | None = None) -> asyncio.Task[R]:
    coordinator = _BOUND.get()
    return (
        asyncio.create_task(coro, name=name) if coordinator is None else coordinator.spawn(coro, kind=kind, name=name)
    )


def start_daemon[R](factory: Callable[[], Awaitable[R]], *, name: str) -> asyncio.Task[R]:
    coordinator = _BOUND.get()

    async def run() -> R:
        if coordinator is not None:
            await coordinator.wait_ready()
        return await factory()

    return asyncio.create_task(run(), name=name)


class MaintenanceMiddleware:
    """HTTP lease охватывает cleanup/stream; audio WS не обходят admission."""

    def __init__(self, app: ASGIApp, *, coordinator: MaintenanceCoordinator) -> None:
        self.app, self.coordinator = app, coordinator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path, kind = scope.get("path", ""), scope["type"]
        guarded = (kind == "http" and path.startswith("/api/")) or (kind == "websocket" and path != "/ws/stream")
        metadata = kind == "http" and scope.get("method") == "GET" and path == "/api/sim/baseline"
        recovery = kind == "http" and scope.get("method") == "POST" and path == "/api/sim/baseline/restore"
        with self.coordinator.bind():
            if not guarded or metadata:
                await self.app(scope, receive, send)
                return
            if self.coordinator.phase != "ready" and not (recovery and self.coordinator.phase == "failed"):
                if kind == "websocket":
                    await send({"type": "websocket.close", "code": 1013})
                else:
                    await Problem(
                        409 if recovery else 503,
                        "Baseline в режиме обслуживания",
                        "Дождитесь завершения; при ошибке повторите baseline restore",
                    ).to_response(path)(scope, receive, send)
                return
            async with self.coordinator.operation("audio" if kind == "websocket" else "http", recovery=recovery):
                await self.app(scope, receive, send)
