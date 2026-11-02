"""Все dialog replies сначала становятся notification и encrypted delivery receipt."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.observability.redaction import redact_tracking_urls
from app.tgbot.configuration import TransportConfiguration


def notification_hash(row: dict[str, Any]) -> str:
    # Только immutable содержимое: status/sent_at/external_ref меняются при доставке.
    material = {key: str(row.get(key)) for key in ("id", "run_id", "signal_id", "client_id", "channel_code", "body")}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def enqueue_reply(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    config: TransportConfiguration,
    *,
    run_id: int,
    chat_id: int,
    reply: dict[str, Any],
    signal_id: int | None = None,
    client_id: int | None = None,
) -> int:
    text = str(reply["reply_text"])
    if len(text.encode("utf-16-le")) // 2 > 4096:
        raise ValueError("telegram_reply_too_large")
    buttons = reply.get("buttons") or []
    keyboard = []
    for button in buttons:
        data = str(button["data"])
        if not 1 <= len(data.encode()) <= 64:
            raise ValueError("telegram_callback_data_invalid")
        keyboard.append([{"text": str(button["text"]), "callback_data": data}])
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    row = await (
        await conn.execute(
            "insert into notifications(run_id,recipient_type,signal_id,client_id,channel_code,template_code,body,status) "
            "values(%s,'client',%s,%s,'telegram_bot','bot_dialogue',%s,'queued') "
            "returning id,delivery_key,run_id,signal_id,client_id,channel_code,body",
            (run_id, signal_id, client_id, redact_tracking_urls(text)),
        )
    ).fetchone()
    assert row is not None
    await _enqueue_payload(conn, config, row, payload)
    return int(row["id"])


async def _enqueue_payload(
    conn: psycopg.AsyncConnection[Any], config: TransportConfiguration, row: dict[str, Any], payload: dict[str, Any]
) -> None:
    await conn.execute(
        "insert into channel_runtime.telegram_deliveries"
        "(delivery_key,bot_id,chat_id,notification_id,run_id,body_hash,payload_enc) "
        "values(%s,%s,%s,%s,%s,%s,pgp_sym_encrypt(%s,%s))",
        (
            row["delivery_key"],
            config.bot_id,
            payload["chat_id"],
            row["id"],
            row["run_id"],
            notification_hash(row),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            config.app_secret,
        ),
    )


async def target_for_notification(
    conn: psycopg.AsyncConnection[Any], config: TransportConfiguration, note: dict[str, Any]
) -> int | None:
    """Service-origin reply либо явный opt-in synthetic client; seed chat IDs не grant."""
    if note["recipient_type"] != "client":
        return None
    async with conn.cursor(row_factory=dict_row) as cur:
        if note["signal_id"] is not None:
            await cur.execute(
                "select coalesce(p.id,s.id) as id,coalesce(p.run_id,s.run_id) as run_id, "
                "coalesce(p.channel_code,s.channel_code) as channel_code,coalesce(p.tracking_token,s.tracking_token) as token, "
                "p.parent_signal_id as ancestor from signals s left join signals p on p.id=s.parent_signal_id where s.id=%s",
                (note["signal_id"],),
            )
            root = await cur.fetchone()
            if (
                root
                and root["channel_code"] == "telegram_bot"
                and root["ancestor"] is None
                and isinstance(root["token"], str)
            ):
                await cur.execute(
                    "select chat_id from channel_runtime.telegram_signal_bindings where bot_id=%s and signal_id=%s and run_id=%s and token_hash=%s",
                    (config.bot_id, root["id"], root["run_id"], hashlib.sha256(root["token"].encode()).hexdigest()),
                )
                grant = await cur.fetchone()
                if grant:
                    return int(grant["chat_id"])
        if note["client_id"] is not None:
            await cur.execute(
                "select b.chat_id from clients c join channel_runtime.telegram_client_bindings b "
                "on b.client_id=c.id and b.client_code=c.public_id and b.chat_id=c.telegram_chat_id "
                "where c.id=%s and b.bot_id=%s",
                (note["client_id"], config.bot_id),
            )
            grant = await cur.fetchone()
            if grant:
                return int(grant["chat_id"])
    return None


async def enqueue_notification(
    conn: psycopg.AsyncConnection[Any], config: TransportConfiguration, notification_id: int
) -> bool:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select * from notifications where id=%s", (notification_id,))
        note = await cur.fetchone()
    if note is None or note["status"] != "queued":
        return False
    chat = await target_for_notification(conn, config, note)
    if chat is None:
        await conn.execute("update notifications set status='failed' where id=%s", (notification_id,))
        return False
    payload = {"chat_id": chat, "text": note["body"], "link_preview_options": {"is_disabled": True}}
    await _enqueue_payload(conn, config, note, payload)
    return True
