"""Нормализатор входящих сообщений (T-207, ДТЗ FR-1.2): любой источник → UnifiedMessage (contracts/events/ingest/unified_message)
→ signals + событие signal.received. Идемпотентность по (source_code, external_id) через ingest_messages."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from app.contracts.registry import validate
from app.feed import service as feed_svc
from app.sim.events import dumps

CHANNELS = {
    "social",
    "call",
    "chat",
    "email",
    "branch",
    "landing",
    "telegram_bot",
    "proactive",
    "review_portal",
    "voice_input",
    "branch_audio",
}


class IngestError(ValueError):
    pass


async def _one(conn: psycopg.AsyncConnection[Any], sql: str, args: tuple[Any, ...]) -> tuple[Any, ...] | None:
    """Выборка кортежем независимо от row_factory соединения (роутеры используют dict_row)."""
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(sql, args)
        return await cur.fetchone()


def from_api_signal(body: dict[str, Any], *, origin: str = "jury", source_code: str = "api") -> dict[str, Any]:
    """POST /api/signals (жюри-режим) → UnifiedMessage."""
    ext = body.get("external_contact") or {}
    return {
        "channel": body.get("channel_code") or "chat",
        "channel_subtype": body.get("channel_subtype"),
        "external_id": body.get("external_id") or f"{source_code}-{uuid.uuid4().hex[:12]}",
        "client": {
            "client_id": body.get("client_id"),
            "contact_hints": {
                k: v
                for k, v in {
                    "phone": ext.get("phone"),
                    "email": ext.get("email"),
                    "nickname": ext.get("nick"),
                    "name": ext.get("name"),
                }.items()
                if v
            }
            or None,
        },
        "text": (body.get("text") or "").strip(),
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "geo": {"source": "contact", "region_code": ext.get("region_code"), "city_id": ext.get("city_id")}
        if ext.get("region_code") or ext.get("city_id")
        else {"source": "none"},
        "origin": origin,
        "meta": {k: v for k, v in body.items() if k in ("voice_meta", "compare_with_mock", "external_post_id")},
    }


def from_sim_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Событие sim/signal → UnifiedMessage (симулятор пока пишет в signals напрямую; функция — для единообразия и тестов)."""
    ext = payload.get("external_contact") or {}
    return {
        "channel": payload["channel"],
        "channel_subtype": None,
        "external_id": f"sim-{payload['signal_id']}",
        "client": {
            "client_id": payload.get("client_id"),
            "contact_hints": {"nickname": ext.get("nick")} if ext.get("nick") else None,
        },
        "text": payload["text"],
        "timestamp": payload["received_sim"],
        "geo": {"source": "client_profile", "region_code": ext.get("region_code")}
        if ext.get("region_code")
        else {"source": "none"},
        "origin": payload.get("origin") or "sim",
        "meta": {
            "source_operation_id": payload.get("source_operation_id"),
            "source_fault_id": payload.get("source_fault_id"),
        },
    }


async def create_signal(
    conn: psycopg.AsyncConnection[Any],
    msg: dict[str, Any],
    *,
    source_code: str,
    run_id: int | None = None,
    sim_time: dt.datetime | None = None,
    emit_event: bool = True,
) -> dict[str, Any]:
    """Валидирует UnifiedMessage, пишет ingest_messages + signals, шлёт NOTIFY. Возвращает IngestResult."""
    msg = {k: v for k, v in msg.items() if v is not None}
    msg.setdefault("client", {})
    if msg["client"].get("contact_hints") is None:
        msg["client"].pop("contact_hints", None)
    if run_id is None:
        row = await _one(conn, "select current_run_id, sim_time from sim_state where id = 1", ())
        run_id = int(row[0]) if row and row[0] else None
        sim_time = sim_time or (row[1] if row else None)
    if run_id is None:
        raise IngestError("нет текущего запуска симуляции (sim_state.current_run_id)")
    errors = validate(msg, "ingest/unified_message")
    if errors:
        await conn.execute(
            "insert into ingest_messages (run_id, source_code, external_id, payload, status, error) values (%s, %s, %s, %s::jsonb, 'rejected', %s) on conflict do nothing",
            (run_id, source_code, msg.get("external_id") or "?", dumps(msg), "; ".join(errors[:3])[:500]),
        )
        return {
            "external_id": msg.get("external_id"),
            "status": "rejected",
            "signal_id": None,
            "error": "; ".join(errors[:3]),
        }
    dup = await _one(
        conn,
        "select signal_id from ingest_messages where source_code = %s and external_id = %s and status = 'accepted'",
        (source_code, msg["external_id"]),
    )
    if dup:
        return {"external_id": msg["external_id"], "status": "duplicate", "signal_id": dup[0], "error": None}
    received_sim = sim_time or dt.datetime.now(dt.UTC)
    hints = msg["client"].get("contact_hints") or {}
    ext = {
        k: v
        for k, v in {
            "nick": hints.get("nickname"),
            "name": hints.get("name"),
            "phone": hints.get("phone"),
            "email": hints.get("email"),
            "region_code": msg["geo"].get("region_code"),
        }.items()
        if v
    } or None
    row = await _one(
        conn,
        "insert into signals (run_id, channel_code, channel_subtype, client_id, external_contact, text, received_sim, status, origin, geo, source_operation_id, source_fault_id, external_post_id) values (%s, %s, %s, %s, %s::jsonb, %s, %s, 'new', %s, %s::jsonb, %s, %s, %s) returning id",
        (
            run_id,
            msg["channel"],
            msg.get("channel_subtype"),
            msg["client"].get("client_id"),
            dumps(ext) if ext else None,
            msg["text"],
            received_sim,
            msg["origin"],
            dumps(msg["geo"]),
            (msg.get("meta") or {}).get("source_operation_id"),
            (msg.get("meta") or {}).get("source_fault_id"),
            (msg.get("meta") or {}).get("external_post_id"),
        ),
    )
    signal_id = int(row[0])  # type: ignore[index]
    meta = msg.get("meta") or {}
    if meta.get("external_post_id"):
        await feed_svc.link_signal(conn, int(meta["external_post_id"]), signal_id)
    elif msg["channel"] in feed_svc.PLATFORM_BY_CHANNEL:
        # публичное обращение без готового поста (сценарий, жюри, API) — создаём пост на эмуляторе площадки (ТЗ 21.2)
        origin = {
            "sim": "background",
            "scenario": "scenario",
            "jury": "demo",
            "telegram_bot": "telegram_bot",
            "api": "api",
        }.get(msg["origin"], "api")
        post = await feed_svc.create_post(
            conn,
            run_id=run_id,
            platform=feed_svc.PLATFORM_BY_CHANNEL[msg["channel"]],
            author_nick=str(hints.get("nickname") or hints.get("name") or f"guest_{signal_id}"),
            text=msg["text"],
            posted_sim=received_sim,
            origin=origin,
            author_client_id=msg["client"].get("client_id"),
            match_confidence=1.0 if msg["client"].get("client_id") else None,
            mentions={
                k: v
                for k, v in {"card_last4": hints.get("card_last4"), "city": (msg.get("meta") or {}).get("city")}.items()
                if v
            },
            signal_id=signal_id,
        )
        await conn.execute("update signals set external_post_id = %s where id = %s", (post["post_id"], signal_id))
    await conn.execute(
        "insert into ingest_messages (run_id, source_code, external_id, payload, status, signal_id) values (%s, %s, %s, %s::jsonb, 'accepted', %s)",
        (run_id, source_code, msg["external_id"], dumps(msg), signal_id),
    )
    if emit_event:
        corr = uuid.uuid4()
        payload = {
            "event_type": "signal.received",
            "signal_id": signal_id,
            "channel": msg["channel"],
            "client_id": msg["client"].get("client_id"),
            "external_contact": ext,
            "text": msg["text"],
            "received_sim": received_sim.isoformat(),
            "origin": msg["origin"],
        }
        env = {
            "run_id": run_id,
            "event_type": "signal.received",
            "sim_time": received_sim.isoformat(),
            "real_time": dt.datetime.now(dt.UTC).isoformat(),
            "correlation_id": str(corr),
            "payload": payload,
        }
        await conn.execute(
            "insert into sim_events (run_id, event_type, payload, sim_time, correlation_id) values (%s, 'signal.received', %s::jsonb, %s, %s)",
            (run_id, dumps(payload), received_sim, corr),
        )
        await conn.execute("select pg_notify('sim_events', %s)", (dumps(env),))
    await conn.execute(
        "select pg_notify('signals', %s)",
        (
            dumps(
                {
                    "type": "created",
                    "run_id": run_id,
                    "source": source_code,
                    "data": {
                        "id": signal_id,
                        "channel_code": msg["channel"],
                        "client_id": msg["client"].get("client_id"),
                        "received_sim": received_sim,
                        "text": msg["text"][:200],
                        "origin": msg["origin"],
                    },
                }
            ),
        ),
    )
    return {"external_id": msg["external_id"], "status": "accepted", "signal_id": signal_id, "error": None}
