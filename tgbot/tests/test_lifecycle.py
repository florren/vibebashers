from __future__ import annotations

import asyncio
import signal

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.methods import GetMe, GetUpdates
from aiogram.types import User

from cx_tgbot import main
from cx_tgbot.backend import BackendClient
from cx_tgbot.polling import poll
from cx_tgbot.updates import dispatcher

TOKEN = "123456:" + "A" * 35
SECRET = b"public-test-vector-only-000000000000"


class FakeSession(BaseSession):
    def __init__(self, error=None):
        super().__init__()
        self.error = error
        self.stop = None
        self.closed = False
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Synthetic", username="ReviewBankBot")
        assert isinstance(method, GetUpdates)
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        self.stop.set()
        return []

    async def close(self):
        self.closed = True

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("downloads forbidden")
        yield b""  # pragma: no cover


@pytest.mark.parametrize("kind", ["rate", "network", "server", "forbidden"])
async def test_actual_sdk_poll_retry_preserves_offset_and_never_logs_upstream_echo(kind, capsys, caplog):
    method = GetUpdates()
    errors = {
        "rate": TelegramRetryAfter(method, TOKEN, retry_after=99),
        "network": TelegramNetworkError(method, TOKEN),
        "server": TelegramServerError(method, TOKEN),
        "forbidden": TelegramForbiddenError(method, TOKEN),
    }
    stop, sleeps = asyncio.Event(), []
    session = FakeSession(errors[kind])
    session.stop = stop

    async def sleep(seconds):
        sleeps.append(seconds)

    async with httpx.AsyncClient(
        base_url="http://backend.test", transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as http:
        async with Bot(token=TOKEN, session=session) as bot:
            result = await poll(bot, dispatcher(BackendClient(http, SECRET)), stop=stop, sleep=sleep)
    if kind == "forbidden":
        assert result == 2 and len(session.calls) == 1 and sleeps == []
    else:
        assert result == 0 and len(session.calls) == 2
        assert sleeps == ([30] if kind == "rate" else [2])
        assert [item.offset for item in session.calls] == [None, None]
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err + caplog.text
    assert session.closed


@pytest.mark.parametrize("mode", ["normal", "sigterm", "external_cancel"])
async def test_cli_owns_signal_handlers_and_closes_fake_sdk_and_http(monkeypatch, mode):
    loop = asyncio.get_running_loop()
    handlers, removed = {}, []
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: handlers.update({sig: callback}))
    monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: removed.append(sig))
    session = FakeSession()
    monkeypatch.setattr(main, "Bot", lambda token: Bot(token=token, session=session))
    original_http = httpx.AsyncClient
    clients = []

    def http(**kwargs):
        client = original_http(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"accepted": True})), **kwargs
        )
        clients.append(client)
        return client

    monkeypatch.setattr(main.httpx, "AsyncClient", http)
    original_poll = main.poll

    async def owned_poll(bot, handler, *, stop, **kwargs):
        session.stop = stop
        if mode == "sigterm":
            handlers[signal.SIGTERM]()
            await asyncio.Event().wait()
        if mode == "external_cancel":
            raise asyncio.CancelledError()
        return await original_poll(bot, handler, stop=stop, **kwargs)

    monkeypatch.setattr(main, "poll", owned_poll)
    config = main.Configuration(TOKEN, SECRET, "http://backend.test")
    if mode == "external_cancel":
        with pytest.raises(asyncio.CancelledError):
            await main.run(config)
    else:
        assert await main.run(config) == 0
    assert session.closed and clients[0].is_closed
    assert set(handlers) == set(removed) == {signal.SIGTERM, signal.SIGINT}


def test_direct_offline_cli_never_constructs_sdk_client(monkeypatch):
    monkeypatch.setattr(main, "Bot", lambda **kwargs: pytest.fail("offline CLI constructed Bot"))
    assert main.main(["--offline"]) == 0


def test_direct_disabled_cli_never_constructs_sdk_client(monkeypatch):
    monkeypatch.setenv("TGBOT_ENABLED", "false")
    monkeypatch.setattr(main, "Bot", lambda **kwargs: pytest.fail("disabled CLI constructed Bot"))
    assert main.main([]) == 2
