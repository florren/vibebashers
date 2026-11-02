"""Все dialog replies сначала становятся notification и encrypted delivery receipt."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

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
    await conn.execute(
        "insert into channel_runtime.telegram_deliveries"
        "(delivery_key,bot_id,chat_id,notification_id,run_id,body_hash,payload_enc) "
        "values(%s,%s,%s,%s,%s,%s,pgp_sym_encrypt(%s,%s))",
        (
            row["delivery_key"],
            config.bot_id,
            chat_id,
            row["id"],
            run_id,
            notification_hash(row),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            config.app_secret,
        ),
    )
    return int(row["id"])
