"""LISTEN/NOTIFY → WebSocket. Каналы pg_notify (contracts/db/schema.sql, раздел NOTIFY) → топики ws/message.schema.json.

Полезная нагрузка pg_notify — JSON: {"type": "...", "data": {...}, "run_id": N?}. Если канал шлёт «сырой» envelope события
симулятора (sim_events), топик вычисляется по семейству события."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import orjson

from app.db.session import listen_connection
from app.logging import get_logger
from app.realtime.hub import hub

log = get_logger(__name__)

CHANNEL_TOPIC: dict[str, str] = {
    "sim_events": "sim",
    "signals": "signals",
    "incidents": "incidents",
    "agent": "agent",
    "agent_tokens": "agent_tokens",
    "notifications": "notifications",
    "db_activity": "db",
    "hitl": "hitl",
    "tasks": "tasks",
    "clients": "clients",
    "bench": "bench",
    "runs": "runs",
    "feed": "feed",
    "abs": "abs",
    "compliance": "compliance",
    "stt": "stt",
    "demo": "demo",
    "ingest": "ingest",
    "escalations": "escalations",
    "tickets": "tickets",
    "zones": "zones",
    "metrics": "metrics",
}
FAMILY_TOPIC = {
    "op": "sim",
    "fault": "sim",
    "client": "clients",
    "team": "sim",
    "sla": "incidents",
    "review": "feed",
    "abs": "abs",
    "compliance": "compliance",
    "ingest": "ingest",
    "escalation": "escalations",
    "zone": "zones",
}


def route(channel: str, payload: str) -> tuple[str, str, dict[str, Any], int | None] | None:
    try:
        body = orjson.loads(payload) if payload else {}
    except orjson.JSONDecodeError:
        body = {"raw": payload}
    topic = CHANNEL_TOPIC.get(channel)
    if topic is None:
        return None
    if "event_type" in body and channel == "sim_events":  # envelope симулятора
        fam = str(body["event_type"]).split(".")[0]
        return FAMILY_TOPIC.get(fam, "sim"), str(body["event_type"]), body, body.get("run_id")
    return topic, str(body.get("type", "updated")), body.get("data", body), body.get("run_id")


class NotifyBridge:
    def __init__(self, channels: list[str] | None = None) -> None:
        self.channels = channels or list(CHANNEL_TOPIC)
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                conn = await listen_connection(self.channels)
                log.info("notify_listen", channels=len(self.channels))
                backoff = 1.0
                async for n in conn.notifies():
                    r = route(n.channel, n.payload)
                    if r:
                        await hub.publish(*r)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("notify_reconnect", error=str(exc)[:200], backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="notify-bridge")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


bridge = NotifyBridge()
