"""Адаптеры ingest_sources (T-207, AGENTS §6.10): polling только воркером, interval_s не меньше 5.

Demo-профиль не ходит на внешние URL: опрашивается встроенная mock-лента.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Any
from urllib.parse import urlparse

import psycopg

from app.config import get_settings
from app.ingest.normalizer import create_signal
from app.logging import get_logger

log = get_logger(__name__)

_INTERNAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})


def is_external_url(url: str | None) -> bool:
    if not url:
        return False
    if "mock-social-feed" in url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host not in _INTERNAL_HOSTS


def _mock_batch(channel: str, cursor: str | None, limit: int = 5) -> list[dict[str, Any]]:
    start = int(cursor or "0")
    now = dt.datetime.now(dt.UTC).isoformat()
    out = []
    for n in range(start + 1, start + 1 + limit):
        out.append(
            {
                "channel": channel,
                "external_id": str(n),
                "client": {"contact_hints": {"nickname": "mock_feed"}},
                "text": f"Сообщение mock-ленты #{n}",
                "timestamp": now,
                "geo": {"source": "none"},
                "origin": "polling",
            }
        )
    return out


async def poll_source(conn: psycopg.AsyncConnection[Any], row: dict[str, Any]) -> dict[str, Any]:
    """Один проход polling-адаптера. Внешний URL в профиле demo не запрашивается."""
    if row["kind"] != "polling":
        raise ValueError("не polling")
    settings = get_settings()
    url = str((row.get("config") or {}).get("url") or "")
    external = bool(row.get("is_external")) or is_external_url(url)
    stats = dict(row.get("stats") or {})
    stats["polls"] = int(stats.get("polls") or 0) + 1
    accepted = duplicates = rejected = 0
    cursor = row.get("cursor")
    if external and settings.profile == "demo":
        stats["last_error"] = "demo: внешний URL не опрашивается"
    else:
        stats["last_error"] = None
        batch = _mock_batch(str(row["channel_code"]), cursor)
        if external:
            batch = []
            stats["last_error"] = "внешний URL помечен is_external; загрузка только mock-ленты"
        for msg in batch:
            res = await create_signal(conn, msg, source_code=str(row["code"]), emit_event=False)
            status = res.get("status")
            if status == "accepted":
                accepted += 1
                cursor = str(msg["external_id"])
            elif status == "duplicate":
                duplicates += 1
                cursor = str(msg["external_id"])
            else:
                rejected += 1
    stats["accepted"] = int(stats.get("accepted") or 0) + accepted
    stats["duplicates"] = int(stats.get("duplicates") or 0) + duplicates
    stats["rejected"] = int(stats.get("rejected") or 0) + rejected
    await conn.execute(
        "update ingest_sources set stats = %s::jsonb, cursor = %s, last_polled_at = now(), is_external = %s where code = %s",
        (json.dumps(stats, ensure_ascii=False), cursor, external, row["code"]),
    )
    return {
        "fetched": accepted + duplicates + rejected,
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
        "cursor": cursor,
    }


async def polling_worker(stop: asyncio.Event) -> None:
    """Фоновый опрос enabled polling-источников не чаще interval_s (минимум 5)."""
    from app.api.common import db, fetch_all

    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
            return
        except TimeoutError:
            pass
        try:
            async with db() as conn:
                rows = await fetch_all(
                    conn,
                    "select code, kind, channel_code, config, enabled, interval_s, last_polled_at, cursor, is_external, stats "
                    "from ingest_sources where enabled and kind = 'polling' and interval_s >= 5",
                )
                now = dt.datetime.now(dt.UTC)
                for row in rows:
                    last = row.get("last_polled_at")
                    if last is not None and (now - last).total_seconds() < int(row["interval_s"]):
                        continue
                    url = (row.get("config") or {}).get("url")
                    if get_settings().profile == "demo" and (row.get("is_external") or is_external_url(url)):
                        continue
                    await poll_source(conn, row)
        except Exception as exc:  # noqa: BLE001 — воркер не должен ронять процесс
            log.warning("ingest_poll_failed", error=str(exc)[:200])
