"""Durable inbound: одна транзакция для draft, receipt и вызывающего dialog handler."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg


class ReceiptConflict(ValueError):
    def __init__(self) -> None:
        super().__init__("telegram_update_id_conflict")


@dataclass
class Turn:
    duplicate: bool
    state: dict[str, Any] = field(repr=False)
    response: dict[str, Any] | None = field(default=None, repr=False)


def lock_id(namespace: str, bot_id: int, ref: int) -> int:
    raw = hashlib.sha256(f"cx.tgbot.v1:{namespace}:{bot_id}:{ref}".encode()).digest()
    return int.from_bytes(raw[:8], "big", signed=True)


class InboundStore:
    def __init__(self, app_secret: str) -> None:
        if len(app_secret.encode()) < 32 or app_secret == "change-me":
            raise ValueError("telegram_storage_secret_not_configured")
        self._secret = app_secret

    async def decrypt(self, conn: psycopg.AsyncConnection[dict[str, Any]], value: bytes) -> dict[str, Any]:
        cursor = await conn.execute("select pgp_sym_decrypt(%s, %s) as value", (value, self._secret))
        row = await cursor.fetchone()
        assert row is not None
        result: object = json.loads(row["value"])
        if not isinstance(result, dict):
            raise ValueError("telegram_storage_object_invalid")
        return result

    @asynccontextmanager
    async def turn(
        self,
        conn: psycopg.AsyncConnection[dict[str, Any]],
        *,
        bot_id: int,
        update_id: int,
        chat_id: int,
        body: bytes,
    ) -> AsyncIterator[Turn]:
        if bot_id <= 0 or chat_id <= 0 or update_id < 0 or len(body) > 32768:
            raise ValueError("telegram_storage_identity_invalid")
        body_hash = hashlib.sha256(body).hexdigest()
        async with conn.transaction():
            # Порядок update → chat одинаков для всех writers. Collision лишь сериализует.
            await conn.execute("select pg_advisory_xact_lock(%s)", (lock_id("update", bot_id, update_id),))
            cursor = await conn.execute(
                "select chat_id, body_hash, response_enc from channel_runtime.telegram_inbound "
                "where bot_id = %s and update_id = %s",
                (bot_id, update_id),
            )
            receipt = await cursor.fetchone()
            if receipt is not None:
                if receipt["chat_id"] != chat_id or receipt["body_hash"] != body_hash:
                    raise ReceiptConflict()
                yield Turn(True, {}, await self.decrypt(conn, receipt["response_enc"]))
                return
            await conn.execute("select pg_advisory_xact_lock(%s)", (lock_id("chat", bot_id, chat_id),))
            cursor = await conn.execute(
                "select state_enc from channel_runtime.telegram_conversations where bot_id = %s and chat_id = %s",
                (bot_id, chat_id),
            )
            row = await cursor.fetchone()
            state = await self.decrypt(conn, row["state_enc"]) if row is not None else {"version": 1, "stage": "role"}
            if state.get("version") != 1:
                raise ValueError("telegram_state_version_unknown")
            turn = Turn(False, state)
            yield turn
            if turn.response is None:
                raise ValueError("telegram_receipt_response_missing")
            state_text = json.dumps(turn.state, ensure_ascii=False, separators=(",", ":"))
            response_text = json.dumps(turn.response, ensure_ascii=False, separators=(",", ":"))
            if max(len(state_text.encode()), len(response_text.encode())) > 32768:
                raise ValueError("telegram_storage_object_too_large")
            await conn.execute(
                "insert into channel_runtime.telegram_conversations(bot_id, chat_id, state_enc) "
                "values (%s, %s, pgp_sym_encrypt(%s, %s)) "
                "on conflict(bot_id, chat_id) do update set state_enc = excluded.state_enc, "
                "revision = telegram_conversations.revision + 1, updated_at = now()",
                (bot_id, chat_id, state_text, self._secret),
            )
            await conn.execute(
                "insert into channel_runtime.telegram_inbound(bot_id, update_id, chat_id, body_hash, response_enc) "
                "values (%s, %s, %s, %s, pgp_sym_encrypt(%s, %s))",
                (bot_id, update_id, chat_id, body_hash, response_text, self._secret),
            )
