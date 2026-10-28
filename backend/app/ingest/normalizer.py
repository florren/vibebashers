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
from app.ingest.red_words import detect
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


def from_landing(
    *,
    contact: dict[str, Any],
    text: str,
    product_code: str | None = None,
    voice_meta: dict[str, Any] | None = None,
    tracking_token: str | None = None,
    parent_signal_id: int | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Форма /claim → UnifiedMessage. product_code остаётся в meta (payload ingest_messages)."""
    hints = {
        k: v
        for k, v in {
            "phone": contact.get("phone"),
            "email": contact.get("email"),
            "nickname": contact.get("nick"),
            "name": contact.get("name"),
        }.items()
        if v
    }
    meta: dict[str, Any] = {}
    if product_code:
        meta["product_code"] = product_code
    if isinstance(voice_meta, dict):
        meta["voice_meta"] = voice_meta
    if tracking_token:
        meta["tracking_token"] = tracking_token
    if parent_signal_id is not None:
        meta["parent_signal_id"] = int(parent_signal_id)
    city_raw = contact.get("city_id")
    geo: dict[str, Any] = {
        "source": "contact",
        "region_code": contact.get("region_code"),
        "city_id": int(city_raw) if city_raw is not None else None,
    }
    return {
        "channel": "landing",
        "channel_subtype": "claim_form",
        "external_id": external_id or f"landing-{uuid.uuid4().hex[:16]}",
        "client": {"contact_hints": hints or None},
        "text": text.strip(),
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "geo": geo,
        "origin": "voice_input" if isinstance(meta.get("voice_meta"), dict) else "landing",
        "meta": meta,
    }


def from_bot(
    *,
    chat_id: int,
    text: str,
    phone: str | None = None,
    email: str | None = None,
    name: str | None = None,
    region_code: str | None = None,
    tracking_token: str | None = None,
    parent_signal_id: int | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Входящее Telegram-бота → UnifiedMessage. client_id не заполняется."""
    hints = {k: v for k, v in {"phone": phone, "email": email, "name": name}.items() if v}
    meta: dict[str, Any] = {"telegram_chat_id": int(chat_id)}
    if tracking_token:
        meta["tracking_token"] = tracking_token
    if parent_signal_id is not None:
        meta["parent_signal_id"] = int(parent_signal_id)
    geo: dict[str, Any] = {"source": "contact", "region_code": region_code} if region_code else {"source": "none"}
    return {
        "channel": "telegram_bot",
        "channel_subtype": "bot",
        "external_id": external_id or f"tg-{chat_id}-{uuid.uuid4().hex[:12]}",
        "client": {"contact_hints": hints or None},
        "text": text.strip(),
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "geo": geo,
        "origin": "telegram_bot",
        "meta": meta,
    }


def from_csi(body: dict[str, Any]) -> dict[str, Any]:
    """CSI → неизменённая UnifiedMessage; разрешённое ВСП добавляет сервер."""
    return {
        "channel": "csi_survey",
        "external_id": body["csi_no"],
        "client": {},
        "text": body["complaint_ru"],
        "timestamp": body.get("received_at") or dt.datetime.now(dt.UTC).isoformat(),
        "geo": {"source": "none"},
        "origin": "api",
        "meta": {"csi_meta": body},
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
    if msg.get("channel") == "csi_survey":
        async with conn.transaction():
            return await _create_signal(
                conn, msg, source_code=source_code, run_id=run_id, sim_time=sim_time, emit_event=emit_event
            )
    return await _create_signal(
        conn, msg, source_code=source_code, run_id=run_id, sim_time=sim_time, emit_event=emit_event
    )


async def _create_signal(
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
    csi_detail = None
    signal_geo = msg.get("geo") or {"source": "none"}
    if msg.get("channel") == "csi_survey":
        from app.ingest.csi import prepare

        csi_detail, signal_geo = await prepare(conn, msg, source_code)
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
    csi_stamp = ((msg.get("meta") or {}).get("csi_meta") or {}).get("received_at") if csi_detail is not None else None
    received_sim = dt.datetime.fromisoformat(csi_stamp) if csi_stamp else (sim_time or dt.datetime.now(dt.UTC))
    hints = msg["client"].get("contact_hints") or {}
    red = detect(msg["text"])
    meta = {**(msg.get("meta") or {}), "red_words": red}
    msg["meta"] = meta
    ext = {
        k: v
        for k, v in {
            "nick": hints.get("nickname"),
            "name": hints.get("name"),
            "phone": hints.get("phone"),
            "email": hints.get("email"),
            "region_code": msg["geo"].get("region_code"),
            "city_id": msg["geo"].get("city_id"),
            "telegram_chat_id": meta.get("telegram_chat_id"),
        }.items()
        if v is not None and v != ""
    } or None
    voice_meta = meta.get("voice_meta")
    parent_signal_id = meta.get("parent_signal_id")
    row = await _one(
        conn,
        "insert into signals (run_id, channel_code, channel_subtype, client_id, external_contact, text, received_sim, "
        "status, origin, geo, source_operation_id, source_fault_id, external_post_id, tracking_token, voice_meta, parent_signal_id) "
        "values (%s, %s, %s, %s, %s::jsonb, %s, %s, 'new', %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s) "
        "returning id, public_id, tracking_token",
        (
            run_id,
            msg["channel"],
            msg.get("channel_subtype"),
            msg["client"].get("client_id"),
            dumps(ext) if ext else None,
            msg["text"],
            received_sim,
            msg["origin"],
            dumps(signal_geo),
            meta.get("source_operation_id"),
            meta.get("source_fault_id"),
            meta.get("external_post_id"),
            meta.get("tracking_token"),
            dumps(voice_meta) if isinstance(voice_meta, dict) else None,
            int(parent_signal_id) if parent_signal_id is not None else None,
        ),
    )
    if row is None:
        raise IngestError("не удалось создать сигнал")
    signal_id = int(row[0])
    await conn.execute(
        "update signals set red_words = %s, flags = %s, meta = meta || %s::jsonb, "
        "classification = case when %s then jsonb_build_object('criticality', 'high') else classification end where id = %s",
        (red["words"], ["red_word"] if red["words"] else [], dumps(meta), bool(red["words"]), signal_id),
    )
    if csi_detail is not None:
        from app.ingest.csi import persist

        await persist(conn, signal_id, csi_detail)
    public_id = str(row[1])
    tracking_out = row[2]
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
        "insert into ingest_messages (run_id, source_code, external_id, payload, status, signal_id) values (%s, %s, %s, %s::jsonb, 'accepted', %s)"
        + (
            " on conflict (source_code,external_id) do update set run_id=excluded.run_id,payload=excluded.payload,status='accepted',signal_id=excluded.signal_id,error=null where ingest_messages.status<>'accepted'"
            if csi_detail is not None
            else ""
        ),
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
    return {
        "external_id": msg["external_id"],
        "status": "accepted",
        "signal_id": signal_id,
        "public_id": public_id,
        "tracking_token": tracking_out,
        "error": None,
    }
