"""Адаптеры ingest_sources (T-207/T-273, ADR-0019): interval_s воркера не меньше 5.

Встроенная синтетика — только явная команда в активном запуске. URL-адаптер пока не реализован.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
import yaml
from psycopg.rows import tuple_row

from app.config import get_settings
from app.ingest.normalizer import create_signal
from app.ingest.synthetic import is_mock_source
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


@lru_cache(maxsize=1)
def _corpus() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[3] / "data/corpus/mock_feed.yaml"
    posts = yaml.safe_load(path.read_text(encoding="utf-8"))["posts"]
    if not isinstance(posts, list) or not posts:
        raise ValueError("пустой mock-корпус")
    return posts


def _mock_batch(
    channel: str, cursor: str | None, *, run_id: int, sim_time: dt.datetime, limit: int
) -> list[dict[str, Any]]:
    start = int(cursor or "0")
    posts = _corpus()
    return [
        {
            "channel": channel,
            "external_id": f"mock:{run_id}:{n}",
            "client": {"contact_hints": {"nickname": posts[(n - 1) % len(posts)]["author"]}},
            "text": posts[(n - 1) % len(posts)]["text"],
            "timestamp": sim_time.isoformat(),
            "geo": {"source": "none"},
            "origin": "polling",
            "meta": {"synthetic_mode": "manual"},
        }
        for n in range(start + 1, start + 1 + limit)
    ]


async def poll_source(
    conn: psycopg.AsyncConnection[Any], row: dict[str, Any], *, manual: bool = False
) -> dict[str, Any]:
    async with conn.transaction():
        return await _poll_source(conn, row, manual=manual)


async def _poll_source(
    conn: psycopg.AsyncConnection[Any], row: dict[str, Any], *, manual: bool = False
) -> dict[str, Any]:
    """Один проход polling-адаптера. Внешний URL в профиле demo не запрашивается."""
    if row["kind"] != "polling":
        raise ValueError("не polling")
    url = str((row.get("config") or {}).get("url") or "")
    external = bool(row.get("is_external")) or is_external_url(url)
    stats = dict(row.get("stats") or {})
    stats["polls"] = int(stats.get("polls") or 0) + 1
    accepted = duplicates = rejected = 0
    cursor = row.get("cursor")
    if external:
        stats["last_error"] = "внешний URL-адаптер не реализован; сообщения не синтезируются"
    elif not is_mock_source(row):
        stats["last_error"] = "URL-адаптер не реализован; для демо явно выберите adapter=mock"
    else:
        if not manual:
            raise ValueError("mock-источник запускается только явным «Опросить сейчас»")
        config = row.get("config") or {}
        if config.get("corpus") not in (None, "", "data/corpus/mock_feed.yaml"):
            raise ValueError("поддерживается только встроенный data/corpus/mock_feed.yaml")
        limit = int(config.get("batch", 5))
        if not 1 <= limit <= 20:
            raise ValueError("batch должен быть от 1 до 20")
        async with conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(
                "select st.current_run_id,st.sim_time,st.running,r.kind,r.status from sim_state st "
                "left join sim_runs r on r.id=st.current_run_id where st.id=1 for share of st"
            )
            state = await cur.fetchone()
        if not state or not state[2] or state[3] == "baseline" or state[4] != "running":
            raise ValueError("синтетический mock требует активного запуска симуляции; baseline/пауза не меняются")
        stats["last_error"] = None
        batch = _mock_batch(str(row["channel_code"]), cursor, run_id=int(state[0]), sim_time=state[1], limit=limit)
        for msg in batch:
            res = await create_signal(conn, msg, source_code=str(row["code"]), run_id=int(state[0]), sim_time=state[1])
            status = res.get("status")
            if status == "accepted":
                accepted += 1
                cursor = str(msg["external_id"]).rsplit(":", 1)[-1]
            elif status == "duplicate":
                duplicates += 1
                cursor = str(msg["external_id"]).rsplit(":", 1)[-1]
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
                    if is_mock_source(row):
                        continue  # Синтетика только по явной команде, не по реальному таймеру.
                    last = row.get("last_polled_at")
                    if last is not None and (now - last).total_seconds() < int(row["interval_s"]):
                        continue
                    url = (row.get("config") or {}).get("url")
                    if get_settings().profile == "demo" and (row.get("is_external") or is_external_url(url)):
                        continue
                    await poll_source(conn, row)
        except Exception as exc:  # noqa: BLE001 — воркер не должен ронять процесс
            log.warning("ingest_poll_failed", error=str(exc)[:200])
