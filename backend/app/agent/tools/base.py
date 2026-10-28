"""ToolContext: соединение, run_id, учёт вызовов инструментов по contracts/events/agent/tool_call.schema.json."""

from __future__ import annotations

import datetime as dt
import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

import orjson
import psycopg

from app.contracts.registry import validate
from app.logging import get_logger
from app.sim.events import dumps

log = get_logger(__name__)
P = ParamSpec("P")
R = TypeVar("R")
MAX_RESULT_BYTES = 4096
SIDE_EFFECT_TOOLS = {
    "create_incident",
    "link_signal_to_incident",
    "update_incident",
    "notify_client",
    "notify_team",
    "create_task",
    "request_human_decision",
    "schedule_followup",
    "close_incident",
    "refund_fee",
    "publish_public_reply",
    "route_to_product_team",
    "route_to_department",
    "notify_customer",
    "escalate_to_manager",
    "request_clarification",
}
# Фасады роутера (ТЗ 9.2): после успеха их вызов сворачивает внутренние tool_call в wraps.
FACADE_TOOLS = {
    "route_to_product_team",
    "route_to_department",
    "notify_customer",
    "escalate_to_manager",
    "request_clarification",
}


class ToolError(RuntimeError):
    pass


@dataclass
class ActFrame:
    """Кадр узла act: контекст фасада, которого нет в аргументах схемы router_tools."""

    signal_id: int
    client_id: int | None
    incident_id: int | None
    link_incident_id: int | None
    spec: dict[str, Any] = field(default_factory=dict)


class ToolContext:
    def __init__(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        run_id: int,
        agent_run_id: int,
        sim_time: dt.datetime,
        llm_source: str = "mock",
    ) -> None:
        self.conn = conn
        self.run_id = run_id
        self.agent_run_id = agent_run_id
        self.sim_time = sim_time
        self.llm_source = llm_source
        self.calls: list[dict[str, Any]] = []  # tool_calls текущего узла (сбрасывает узел)
        self.pending_wraps: list[str] = []  # внутренние имена, которые фасад свернёт в wraps
        self.act_frame: ActFrame | None = None

    def take_calls(self) -> list[dict[str, Any]]:
        calls, self.calls = self.calls, []
        return calls

    async def notify(self, channel: str, type_: str, data: dict[str, Any]) -> None:
        await self.conn.execute(
            "select pg_notify(%s, %s)", (channel, dumps({"type": type_, "run_id": self.run_id, "data": data}))
        )

    async def fetchone(self, sql: str, args: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        cur = await self.conn.execute(sql, args)
        return await cur.fetchone()

    async def fetchall(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        cur = await self.conn.execute(sql, args)
        return await cur.fetchall()


def _compact(result: Any) -> Any:
    raw = dumps(result)
    if len(raw) <= MAX_RESULT_BYTES:
        return orjson.loads(raw)
    if isinstance(result, list):
        out = list(result)
        while out and len(dumps(out)) > MAX_RESULT_BYTES:
            out = out[: max(1, len(out) * 2 // 3)]
        return out
    if isinstance(result, dict):
        return {**result, "_truncated": True, **{k: v for k, v in result.items() if not isinstance(v, (list, dict))}}
    return raw[:MAX_RESULT_BYTES]


def tool(name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Декоратор: замер времени, запись ToolCall (валидный по схеме) в ctx.calls, маскирование ошибок в ok=false."""

    def deco(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            ctx = next(v for v in bound.arguments.values() if isinstance(v, ToolContext))
            call_args = {k: v for k, v in bound.arguments.items() if not isinstance(v, ToolContext)}
            t0 = time.perf_counter()
            calls_mark = len(ctx.calls)
            wraps_mark = len(ctx.pending_wraps)
            rec: dict[str, Any] = {
                "name": name,
                "args": orjson.loads(dumps(call_args)),
                "ok": True,
                "side_effect": name in SIDE_EFFECT_TOOLS,
                "source": ctx.llm_source,
            }
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                del ctx.pending_wraps[wraps_mark:]
                rec.update(
                    ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}", ms=int((time.perf_counter() - t0) * 1000)
                )
                ctx.calls.append(rec)
                log.warning("tool_failed", tool=name, error=rec["error"])
                raise
            new_wraps = ctx.pending_wraps[wraps_mark:]
            if name in FACADE_TOOLS and new_wraps:
                # Внутренние записи этого вызова остаются только в wraps фасада (ТЗ 9.2, §20.6 п.20).
                del ctx.calls[calls_mark:]
                del ctx.pending_wraps[wraps_mark:]
                rec["wraps"] = list(new_wraps)
            rec["ms"] = int((time.perf_counter() - t0) * 1000)
            rec["result"] = _compact(result)
            errors = validate(rec, "agent/tool_call")
            if errors:  # не роняем агента из-за формата записи — но логируем
                log.warning("tool_call_invalid", tool=name, errors=errors[:2])
            ctx.calls.append(rec)
            return result

        return wrapper

    return deco


def mask_name(full: str | None) -> str:
    """«Имя Ф.» → имя (обращение в текстах клиенту без фамилии)."""
    return (full or "Уважаемый клиент").split()[0]
