from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from starlette.requests import Request

from app.config import get_settings
from app.main import create_app
from app.tgbot.configuration import TransportConfiguration
from app.tgbot.liveness import BotLiveness, credential_ref, running_username

CONFIG = TransportConfiguration(
    123456,
    "123456:" + "A" * 35,
    b"public-test-transport-vector-000000000000",
    "public-test-storage-vector-000000000000",
    "https://bank.invalid",
)
PATH = "/api/internal/tgbot/heartbeat"


def setup_settings(monkeypatch):
    settings = get_settings()
    for key, value in {
        "tgbot_enabled": True,
        "telegram_bot_token": CONFIG.token,
        "tgbot_internal_secret": CONFIG.secret.decode(),
        "app_secret": CONFIG.app_secret,
        "tgbot_public_base_url": CONFIG.public_origin,
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def test_monotonic_expiry_rotation_and_restart_never_reuse_old_readiness():
    now = [100.0]
    proof = BotLiveness(clock=lambda: now[0])
    assert proof.username(CONFIG) is None
    proof.observe(CONFIG, "ReviewBankBot")
    assert proof.username(CONFIG) == "ReviewBankBot"
    assert proof.username(replace(CONFIG, token=CONFIG.token[:-1] + "B")) is None
    assert proof.username(replace(CONFIG, secret=b"different-public-test-secret00000000")) is None
    assert proof.username(replace(CONFIG, app_secret="different-public-storage-secret00000000")) is None
    assert proof.username(replace(CONFIG, public_origin="https://other.invalid")) is None
    now[0] = 190.0
    assert proof.username(CONFIG) is None
    now[0] = 99.0
    assert proof.username(CONFIG) is None
    assert BotLiveness().username(CONFIG) is None


@pytest.mark.parametrize(
    "username", ["x", "../OtherBot", "bank.invalid/OtherBot", "@ReviewBot", "ordinary_user", "БанкBot"]
)
def test_username_never_becomes_untrusted_url(username):
    with pytest.raises(ValueError, match="telegram_bot_username_invalid"):
        BotLiveness().observe(CONFIG, username)


def test_live_poll_proof_also_requires_owned_delivery_worker(monkeypatch):
    settings = setup_settings(monkeypatch)
    app = create_app()
    app.state.tgbot_liveness = BotLiveness()
    app.state.tgbot_liveness.observe(CONFIG, "ReviewBankBot")
    assert running_username(app, settings) is None
    app.state.tgbot_task = SimpleNamespace(done=lambda: False)
    assert running_username(app, settings) == "ReviewBankBot"
    app.state.tgbot_task = SimpleNamespace(done=lambda: True)
    assert running_username(app, settings) is None
    monkeypatch.setattr(settings, "tgbot_enabled", False)
    assert running_username(app, settings) is None
    monkeypatch.setattr(settings, "tgbot_enabled", True)
    monkeypatch.setattr(settings, "tgbot_internal_secret", "short")
    assert running_username(app, settings) is None


def signed(raw, *, path=PATH):
    stamp = str(int(time.time()))
    payload = "\n".join(("cx-tgbot-v1", stamp, "POST", path, hashlib.sha256(raw).hexdigest())).encode()
    return {
        "Content-Type": "application/json",
        "X-CX-Tg-Timestamp": stamp,
        "X-CX-Tg-Signature": hmac.new(CONFIG.secret, payload, hashlib.sha256).hexdigest(),
    }


async def test_signed_heartbeat_and_qr_use_actual_username_without_db_or_external_calls(monkeypatch):
    setup_settings(monkeypatch)
    app = create_app()
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("heartbeat/QR must not call PostgreSQL")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", forbidden)
    raw = json.dumps(
        {"bot_id": CONFIG.bot_id, "username": "ReviewBankBot", "credential_ref": credential_ref(CONFIG)}
    ).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://backend.test") as client:
        assert (await client.get("/api/public/bot/qr")).status_code == 503
        assert (await client.post(PATH, content=raw)).status_code == 401
        # Подпись соседнего inbound path не переносится на heartbeat.
        assert (
            await client.post(PATH, content=raw, headers=signed(raw, path="/api/internal/tgbot/inbound"))
        ).status_code == 401
        assert (await client.post(PATH, content=raw, headers=signed(raw))).json() == {"accepted": True}
        assert (await client.get("/api/public/bot/qr")).status_code == 503
        app.state.tgbot_task = SimpleNamespace(done=lambda: False)
        from app.api import public

        payloads = []
        original = public._qr_svg
        monkeypatch.setattr(public, "_qr_svg", lambda value: (payloads.append(value), original(value))[1])
        public._bot_qr.cache_clear()
        first = await client.get("/api/public/bot/qr")
        second = await client.get("/api/public/bot/qr")
        assert first.status_code == second.status_code == 200
        assert first.text == second.text and "<svg" in first.text
        assert payloads == ["https://t.me/ReviewBankBot"]
        assert first.headers["cache-control"] == "no-store"
        app.state.tgbot_task = None
        assert (await client.get("/api/public/bot/qr")).status_code == 503
    assert calls == []


@pytest.mark.parametrize(
    "patch,status",
    [
        ({"bot_id": 123457}, 409),
        ({"credential_ref": "0" * 64}, 409),
        ({"bot_id": True}, 422),
        ({"username": "../WrongBot"}, 422),
        ({"extra": "x"}, 422),
    ],
)
async def test_heartbeat_namespace_and_input_fail_closed(monkeypatch, patch, status):
    setup_settings(monkeypatch)
    app = create_app()
    raw = json.dumps(
        {"bot_id": CONFIG.bot_id, "username": "ReviewBankBot", "credential_ref": credential_ref(CONFIG), **patch}
    ).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://backend.test") as client:
        response = await client.post(PATH, content=raw, headers=signed(raw))
        assert response.status_code == status
    assert not hasattr(app.state, "tgbot_liveness")


async def test_health_never_reports_running_from_token_alone(monkeypatch):
    from app.api.health import get_health

    settings = setup_settings(monkeypatch)
    app = create_app()
    request = Request({"type": "http", "app": app})

    class Result:
        def scalar_one_or_none(self):
            return False

        def all(self):
            return []

    class Session:
        async def execute(self, statement):
            return Result()

    session = Session()
    health = await get_health(request, session)
    assert health["tgbot"] == "error" and health["tgbot_username"] is None
    app.state.tgbot_task = SimpleNamespace(done=lambda: False)
    proof = app.state.tgbot_liveness = BotLiveness(clock=lambda: 100.0)
    proof.observe(CONFIG, "ReviewBankBot")
    health = await get_health(request, session)
    assert health["tgbot"] == "running" and health["tgbot_username"] == "ReviewBankBot"
    proof.clock = lambda: 190.0
    health = await get_health(request, session)
    assert health["tgbot"] == "error" and health["tgbot_username"] is None
    monkeypatch.setattr(settings, "tgbot_enabled", False)
    assert (await get_health(request, session))["tgbot"] == "disabled"
