"""Хаб WebSocket: подписки по топикам и фильтрам, рассылка сообщений по схеме contracts/events/ws/message.schema.json."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import orjson
from fastapi import WebSocket

from app.logging import get_logger

log = get_logger(__name__)
TOPICS = {
    "signals",
    "agent",
    "agent_tokens",
    "incidents",
    "notifications",
    "sim",
    "db",
    "hitl",
    "tasks",
    "clients",
    "bench",
    "system",
    "runs",
    "feed",
    "abs",
    "compliance",
    "stt",
    "demo",
    "ingest",
    "escalations",
    "tickets",
    "zones",
    "metrics",
}


@dataclass
class Client:
    ws: WebSocket
    topics: set[str] = field(default_factory=set)
    filters: dict[str, Any] = field(default_factory=dict)

    def wants(self, topic: str, data: dict[str, Any]) -> bool:
        if topic not in self.topics and topic != "system":
            return False
        for k, v in self.filters.items():
            if k in data and data[k] != v:
                return False
        return True


class Hub:
    def __init__(self) -> None:
        self._clients: dict[int, Client] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> Client:
        await ws.accept()
        c = Client(ws)
        async with self._lock:
            self._clients[id(ws)] = c
        return c

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(id(ws), None)

    @property
    def size(self) -> int:
        return len(self._clients)

    @staticmethod
    def message(topic: str, type_: str, data: dict[str, Any], run_id: int | None = None) -> str:
        body: dict[str, Any] = {"topic": topic, "type": type_, "ts": dt.datetime.now(dt.UTC).isoformat(), "data": data}
        if run_id is not None:
            body["run_id"] = run_id
        return orjson.dumps(body).decode()

    async def publish(self, topic: str, type_: str, data: dict[str, Any], run_id: int | None = None) -> int:
        if topic not in TOPICS:
            log.warning("ws_unknown_topic", topic=topic)
        payload = self.message(topic, type_, data, run_id)
        sent, dead = 0, []
        for key, c in list(self._clients.items()):
            if not c.wants(topic, data):
                continue
            try:
                await c.ws.send_text(payload)
                sent += 1
            except Exception:
                dead.append(key)
        for key in dead:
            self._clients.pop(key, None)
        return sent

    async def handle_command(self, c: Client, raw: str | bytes) -> None:
        try:
            cmd = orjson.loads(raw)
        except orjson.JSONDecodeError:
            await c.ws.send_text(self.message("system", "error", {"detail": "невалидный JSON"}))
            return
        t = cmd.get("type")
        if t == "subscribe":
            c.topics |= {x for x in cmd.get("topics", []) if x in TOPICS}
            c.filters.update(cmd.get("filters") or {})
            await c.ws.send_text(
                self.message("system", "subscribed", {"topics": sorted(c.topics), "filters": c.filters})
            )
        elif t == "unsubscribe":
            c.topics -= set(cmd.get("topics", []))
            await c.ws.send_text(
                self.message("system", "subscribed", {"topics": sorted(c.topics), "filters": c.filters})
            )
        elif t == "ping":
            await c.ws.send_text(self.message("system", "pong", {}))
        else:
            await c.ws.send_text(self.message("system", "error", {"detail": f"неизвестная команда {t!r}"}))


hub = Hub()
