from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetMe, GetUpdates
from aiogram.types import User
from app.tgbot.signature import verify_signature

from cx_tgbot.backend import BackendClient, BackendUnavailable
from cx_tgbot.polling import poll

SECRET = b"public-test-vector-only-000000000000"
TOKEN = "123456:" + "A" * 35
REF = hmac.new(SECRET, b"cx-tgbot-credential-v1:" + TOKEN.encode(), hashlib.sha256).hexdigest()


async def test_heartbeat_signature_is_bound_to_exact_path_and_actual_username():
    seen = []

    async def handle(request):
        verify_signature(
            SECRET,
            method=request.method,
            path=request.url.path,
            body=request.content,
            timestamp=request.headers["X-CX-Tg-Timestamp"],
            signature=request.headers["X-CX-Tg-Signature"],
        )
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"accepted": True})

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        await BackendClient(http, SECRET).heartbeat(bot_id=123456, username="ReviewBankBot", token=TOKEN)
    assert seen == [
        ("/api/internal/tgbot/heartbeat", {"bot_id": 123456, "username": "ReviewBankBot", "credential_ref": REF})
    ]


@pytest.mark.parametrize("status,expected", [(503, 0), (401, 2)])
async def test_failed_health_receipt_does_not_ack_update_or_hide_permanent_failure(status, expected):
    stop = asyncio.Event()
    offsets, feeds, sleeps = [], [], []
    update = SimpleNamespace(update_id=71)
    heartbeats = 0

    async def get_updates(**kwargs):
        offsets.append(kwargs["offset"])
        return [update]

    async def feed_update(bot, item):
        feeds.append(item.update_id)
        stop.set()

    async def heartbeat():
        nonlocal heartbeats
        heartbeats += 1
        if heartbeats == 1:
            raise BackendUnavailable(status)

    async def sleep(seconds):
        sleeps.append(seconds)

    result = await poll(
        SimpleNamespace(get_updates=get_updates),
        SimpleNamespace(feed_update=feed_update),
        stop=stop,
        on_poll=heartbeat,
        sleep=sleep,
    )
    assert result == expected
    assert offsets == ([None, None] if status == 503 else [None])
    assert feeds == ([71] if status == 503 else [])
    assert sleeps == ([2] if status == 503 else [])


async def test_empty_successful_poll_still_reports_liveness():
    stop = asyncio.Event()
    calls = []

    async def get_updates(**kwargs):
        return []

    async def heartbeat():
        calls.append("poll-proof")
        stop.set()

    async def forbidden(*args):
        pytest.fail("empty poll must not dispatch any update")

    assert (
        await poll(
            SimpleNamespace(get_updates=get_updates),
            SimpleNamespace(feed_update=forbidden),
            stop=stop,
            on_poll=heartbeat,
        )
        == 0
    )
    assert calls == ["poll-proof"]


@pytest.mark.parametrize("identity", ["valid", "wrong_id", "missing_username"])
async def test_actual_cli_getme_identity_precedes_poll_proof_and_sessions_close(monkeypatch, identity):
    from cx_tgbot import main

    class FakeSession(BaseSession):
        def __init__(self):
            super().__init__()
            self.methods = []
            self.stop = None
            self.closed = False

        async def make_request(self, bot, method, timeout=None):
            self.methods.append(type(method))
            if isinstance(method, GetMe):
                return User(
                    id=123457 if identity == "wrong_id" else 123456,
                    is_bot=True,
                    first_name="Synthetic",
                    username=None if identity == "missing_username" else "ReviewBankBot",
                )
            assert isinstance(method, GetUpdates)
            self.stop.set()
            return []

        async def close(self):
            self.closed = True

        async def stream_content(self, *args, **kwargs):
            raise AssertionError("downloads forbidden")
            yield b""  # pragma: no cover

    session = FakeSession()
    requests = []

    async def backend(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    original_http = httpx.AsyncClient
    monkeypatch.setattr(
        main.httpx, "AsyncClient", lambda **kwargs: original_http(transport=httpx.MockTransport(backend), **kwargs)
    )
    monkeypatch.setattr(main, "Bot", lambda token: Bot(token=token, session=session))
    original_poll = main.poll

    async def real_poll(bot, dispatcher, *, stop, **kwargs):
        session.stop = stop
        return await original_poll(bot, dispatcher, stop=stop, **kwargs)

    monkeypatch.setattr(main, "poll", real_poll)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *args: None)
    monkeypatch.setattr(loop, "remove_signal_handler", lambda *args: None)
    config = main.Configuration("123456:" + "A" * 35, SECRET, "http://backend.test")
    if identity == "valid":
        assert await main.run(config) == 0
        assert session.methods == [GetMe, GetUpdates]
        assert requests == [{"bot_id": 123456, "username": "ReviewBankBot", "credential_ref": REF}]
    else:
        with pytest.raises(main.InvalidConfiguration, match="telegram_bot_identity_invalid"):
            await main.run(config)
        assert session.methods == [GetMe] and requests == []
    assert session.closed
