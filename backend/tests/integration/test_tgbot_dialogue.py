"""Подписанный real API и PostgreSQL; delivery worker/Telegram сеть выключены."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

BOT = 123457
TOKEN = f"{BOT}:" + "A" * 35
SECRET = "public-test-transport-vector-000000000000"
APP_SECRET = "public-test-storage-vector-000000000000"
PATH = "/api/internal/tgbot/inbound"


@pytest.fixture
def dialogue(seeded, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", seeded)
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "tgbot_enabled", True)
    monkeypatch.setattr(settings, "tgbot_internal_secret", SECRET)
    monkeypatch.setattr(settings, "tgbot_public_base_url", "https://bank.invalid")
    monkeypatch.setattr(settings, "app_secret", APP_SECRET)
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, autocommit=True) as conn:
        for table in ("telegram_inbound", "telegram_conversations", "telegram_deliveries", "telegram_chat_rate"):
            conn.execute(f"delete from channel_runtime.{table} where bot_id=%s", (BOT,))
    return dsn


def send(client, update, text="", *, chat=424243, kind="message", payload=None, language="en"):
    body = {
        "bot_id": BOT,
        "update_id": update,
        "chat_id": chat,
        "kind": kind,
        "text": text,
        "payload": {"language_code": language, **(payload or {})},
    }
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    signing = "\n".join(("cx-tgbot-v1", stamp, "POST", PATH, hashlib.sha256(raw).hexdigest())).encode()
    signature = hmac.new(SECRET.encode(), signing, hashlib.sha256).hexdigest()
    return client.post(
        PATH,
        content=raw,
        headers={"Content-Type": "application/json", "X-CX-Tg-Timestamp": stamp, "X-CX-Tg-Signature": signature},
    )


def accepted(response):
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["accepted"] is True
    return result


def test_restart_duplicate_and_real_message_flow_queue_exactly_once_without_delivery(dialogue):
    with TestClient(create_app()) as client:
        start = accepted(send(client, 71, "/start"))
        assert "Hello" in start["reply_text"]
        assert accepted(send(client, 71, "/start")) == start
        conflict = send(client, 71, "changed")
        assert conflict.status_code == 409
    with TestClient(create_app()) as client:
        accepted(send(client, 72, kind="callback", payload={"callback_data": "not_client"}))
        accepted(send(client, 73, "I cannot open a deposit in the Bank application"))
        rejected = accepted(send(client, 74, "+7 999 123-45-67"))
        assert "fictional" in rejected["reply_text"].lower() or "900" in rejected["reply_text"]
        accepted(send(client, 75, "visitor@example.com"))
        with psycopg.connect(dialogue) as conn:
            region = conn.execute("select code from regions order by code limit 1").fetchone()[0]
        result = accepted(send(client, 76, region))
        assert result["signal_id"] and "https://bank.invalid/track/" in result["reply_text"]
        status = accepted(send(client, 77, "/status"))
        assert "SIG-" in status["reply_text"]
        duplicate = accepted(send(client, 76, region))
        assert duplicate == result
    with psycopg.connect(dialogue) as conn:
        receipts = conn.execute(
            "select count(*) from channel_runtime.telegram_inbound where bot_id=%s", (BOT,)
        ).fetchone()[0]
        notes = conn.execute(
            "select n.status,n.sent_at,n.external_ref,n.body,pgp_sym_decrypt(d.payload_enc,%s) from channel_runtime.telegram_deliveries d join notifications n on n.delivery_key=d.delivery_key where d.bot_id=%s order by n.id",
            (APP_SECRET, BOT),
        ).fetchall()
        assert receipts == len(notes) == 7
        assert all(row[0] == "queued" and row[1] is None and row[2] is None for row in notes)
        token = result["tracking_token"]
        assert all(token not in row[3] for row in notes)
        assert token in notes[-2][4]
        signal = conn.execute(
            "select client_id,external_contact from signals where id=%s", (result["signal_id"],)
        ).fetchone()
        assert signal[0] is None and signal[1]["telegram_chat_id"] == 424243


def test_explicit_language_and_stale_signal_binding_do_not_attach_to_reused_id(dialogue):
    with TestClient(create_app()) as client:
        accepted(send(client, 81, "/start"))
        accepted(send(client, 82, "/lang ru"))
        accepted(send(client, 83, kind="callback", payload={"callback_data": "not_client"}))
        reply = accepted(send(client, 84, "The Bank application does not open my deposit"))
        assert "Укажите" in reply["reply_text"]
        accepted(send(client, 85, "visitor@example.com"))
        with psycopg.connect(dialogue) as conn:
            region = conn.execute("select code from regions order by code limit 1").fetchone()[0]
        result = accepted(send(client, 86, region))
        with psycopg.connect(dialogue) as conn:
            conn.execute(
                "update signals set tracking_token='different-synthetic-owner-token' where id=%s",
                (result["signal_id"],),
            )
        status = accepted(send(client, 87, "/status"))
        assert "не найдено" in status["reply_text"]
        append = accepted(send(client, 88, "Additional details about the same issue"))
        assert append["signal_id"] is None
        forbidden = accepted(send(client, 89, kind="callback", payload={"callback_data": "accept:1"}))
        assert "Неизвестная кнопка" in forbidden["reply_text"]
    with psycopg.connect(dialogue) as conn:
        assert (
            conn.execute("select count(*) from signals where parent_signal_id=%s", (result["signal_id"],)).fetchone()[0]
            == 0
        )


def test_synthetic_client_code_binding_cannot_replace_other_chat_and_is_revalidated(dialogue):
    with psycopg.connect(dialogue) as conn:
        client_id, code = conn.execute(
            "select id,public_id from clients where is_active and telegram_chat_id is null order by id limit 1"
        ).fetchone()
    with TestClient(create_app()) as client:
        accepted(send(client, 91, "/start"))
        accepted(send(client, 92, kind="callback", payload={"callback_data": "is_client"}))
        bound = accepted(send(client, 93, code))
        assert code in bound["reply_text"]
        other = accepted(send(client, 94, f"/bind {code}", chat=424244))
        assert "unavailable" in other["reply_text"]
        accepted(send(client, 95, "The Bank application does not open my deposit"))
        accepted(send(client, 96, "visitor@example.com"))
        with psycopg.connect(dialogue) as conn:
            assert (
                conn.execute("select telegram_chat_id from clients where id=%s", (client_id,)).fetchone()[0] == 424243
            )
            region = conn.execute("select region_code from clients where id=%s", (client_id,)).fetchone()[0]
            conn.execute("update clients set telegram_chat_id=null where id=%s", (client_id,))
        stale = accepted(send(client, 97, region))
        assert stale["signal_id"] is None and "expired" in stale["reply_text"]
        accepted(send(client, 98, "/start"))
        accepted(send(client, 99, f"/bind {code}"))
        accepted(send(client, 100, "The Bank application does not open my deposit"))
        accepted(send(client, 101, "visitor@example.com"))
        result = accepted(send(client, 102, region))
        with psycopg.connect(dialogue) as conn:
            assert (
                conn.execute("select client_id from signals where id=%s", (result["signal_id"],)).fetchone()[0]
                == client_id
            )
        accepted(send(client, 103, "/unbind"))
    with psycopg.connect(dialogue) as conn:
        assert conn.execute("select telegram_chat_id from clients where id=%s", (client_id,)).fetchone()[0] is None
