from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import psycopg
import pytest

from app.config import get_settings
from app.main import create_app

SECRET = "public-test-transport-vector-000000000000"
TOKEN = "123456:" + "A" * 35


@pytest.fixture
def guarded_app(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tgbot_enabled", True)
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "tgbot_internal_secret", SECRET)
    monkeypatch.setattr(settings, "tgbot_public_base_url", "https://bank.invalid")
    monkeypatch.setattr(settings, "app_secret", "public-test-storage-vector-000000000000")
    app = create_app()
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("unauthorized/invalid input reached PostgreSQL")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", forbidden)
    return app, calls, settings


def headers(raw):
    stamp = str(int(time.time()))
    payload = "\n".join(
        ("cx-tgbot-v1", stamp, "POST", "/api/internal/tgbot/inbound", hashlib.sha256(raw).hexdigest())
    ).encode()
    signature = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-CX-Tg-Timestamp": stamp, "X-CX-Tg-Signature": signature}


@pytest.mark.parametrize(
    "case,status",
    [
        ("unsigned", 401),
        ("bad_signature", 401),
        ("oversize", 413),
        ("wrong_bot", 409),
        ("boolean_chat", 422),
        ("huge_chat", 422),
        ("missing_update", 422),
    ],
)
async def test_real_asgi_rejects_before_db_and_never_echoes_secrets(guarded_app, case, status):
    app, calls, _ = guarded_app
    body = {"bot_id": 123456, "chat_id": 123, "update_id": 71, "kind": "message", "text": "/start"}
    if case == "wrong_bot":
        body["bot_id"] = 123457
    elif case == "boolean_chat":
        body["chat_id"] = True
    elif case == "huge_chat":
        body["chat_id"] = 2**64
    elif case == "missing_update":
        body.pop("update_id")
    elif case == "oversize":
        body["text"] = "x" * 32769
    raw = json.dumps(body).encode()
    signed = headers(raw)
    if case == "unsigned":
        signed = {}
    elif case == "bad_signature":
        signed["X-CX-Tg-Signature"] = "0" * 64
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://backend.test") as client:
        response = await client.post("/api/internal/tgbot/inbound", content=raw, headers=signed)
    assert response.status_code == status, response.text
    assert calls == []
    assert TOKEN not in response.text and SECRET not in response.text
    if status != 422:
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_disabled_transport_fails_closed_before_body_validation_and_db(guarded_app, monkeypatch):
    app, calls, settings = guarded_app
    monkeypatch.setattr(settings, "tgbot_enabled", False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://backend.test") as client:
        response = await client.post("/api/internal/tgbot/inbound", content=b"invalid json")
    assert response.status_code == 503 and calls == []


async def test_invalid_enabled_configuration_fails_closed_before_db(guarded_app, monkeypatch):
    app, calls, settings = guarded_app
    monkeypatch.setattr(settings, "telegram_bot_token", "invalid-public-test-vector")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://backend.test") as client:
        response = await client.post("/api/internal/tgbot/inbound", content=b"invalid json")
    assert response.status_code == 503 and calls == []
    assert "invalid-public-test-vector" not in response.text
