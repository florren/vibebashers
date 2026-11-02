from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from app.tgbot.signature import verify_signature

from cx_tgbot.backend import BackendClient
from cx_tgbot.polling import poll
from cx_tgbot.updates import BackendRejected, dispatcher, forward

SECRET = b"public-test-vector-only-000000000000"
NOW = 1_800_000_000


class FakeSession(BaseSession):
    def __init__(self, updates=(), stop=None):
        super().__init__()
        self.updates = list(updates)
        self.calls = []
        self.stop = stop

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if self.updates:
            return [self.updates.pop(0)]
        self.stop.set()
        return []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("downloads forbidden")
        yield b""  # pragma: no cover


def message_update(*, chat_type="private", is_bot=False):
    return Update(
        update_id=71,
        message=Message(
            message_id=12,
            date=datetime(2026, 11, 2, tzinfo=UTC),
            chat=Chat(id=101, type=chat_type),
            from_user=User(id=101, is_bot=is_bot, first_name="Synthetic", language_code="en-GB"),
            text="/start",
        ),
    )


def bot(session):
    # Публичная синтетическая форма, не рабочий token.
    return Bot(token="123456:" + "A" * 35, session=session)


async def test_actual_aiogram_message_projection_and_backend_signature():
    received = []

    async def handle(request):
        verify_signature(
            SECRET,
            method=request.method,
            path=request.url.path,
            body=request.content,
            timestamp=request.headers["X-CX-Tg-Timestamp"],
            signature=request.headers["X-CX-Tg-Signature"],
            now=NOW,
        )
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True, "update_id": 71})

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        session = FakeSession()
        async with bot(session) as instance:
            await dispatcher(BackendClient(http, SECRET, clock=lambda: NOW)).feed_update(instance, message_update())
    assert received == [
        {
            "chat_id": 101,
            "kind": "message",
            "text": "/start",
            "payload": {"message_id": 12, "language_code": "en"},
            "update_id": 71,
        }
    ]
    assert session.calls == []


@pytest.mark.parametrize("chat_type,is_bot", [("group", False), ("private", True)])
async def test_other_chats_and_bot_messages_are_not_forwarded(chat_type, is_bot):
    calls = []

    async def handle(request):
        calls.append(request)
        raise AssertionError("unexpected HTTP")

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        async with bot(FakeSession()) as instance:
            await dispatcher(BackendClient(http, SECRET)).feed_update(
                instance, message_update(chat_type=chat_type, is_bot=is_bot)
            )
    assert calls == []


async def test_callback_is_acknowledged_only_after_backend_accepts():
    session = FakeSession()

    async def handle(request):
        assert session.calls == []
        event = json.loads(request.content)
        assert event["kind"] == "callback"
        assert event["payload"]["callback_data"] == "is_client"
        return httpx.Response(200, json={"accepted": True, "update_id": 72})

    update = Update(
        update_id=72,
        callback_query=CallbackQuery(
            id="synthetic-callback",
            from_user=User(id=101, is_bot=False, first_name="Synthetic"),
            chat_instance="synthetic-instance",
            data="is_client",
            message=message_update().message,
        ),
    )
    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        async with bot(session) as instance:
            await dispatcher(BackendClient(http, SECRET)).feed_update(instance, update)
    assert len(session.calls) == 1 and isinstance(session.calls[0], AnswerCallbackQuery)


async def test_transient_error_retries_same_event_before_ack():
    received, sleeps = [], []

    async def handle(request):
        received.append(json.loads(request.content))
        return httpx.Response(503 if len(received) == 1 else 200, json={"accepted": True, "update_id": 71})

    async def sleep(seconds):
        sleeps.append(seconds)

    event = {"update_id": 71, "chat_id": 101}
    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        await forward(BackendClient(http, SECRET), event, sleep)
    assert received == [event, event] and sleeps == [2]


@pytest.mark.parametrize("ack", [{}, {"accepted": True, "update_id": True}, {"accepted": True, "update_id": 71.0}])
async def test_malformed_ack_does_not_advance_polling(ack):
    async def handle(request):
        return httpx.Response(200, json=ack)

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(BackendRejected):
            await forward(BackendClient(http, SECRET), {"update_id": 71})


@pytest.mark.parametrize("status", [200, 401])
async def test_actual_polling_advances_offset_only_after_acceptance(status):
    async def handle(request):
        return httpx.Response(status, json={"accepted": True, "update_id": 71})

    stop = asyncio.Event()
    session = FakeSession([message_update()], stop)
    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        async with bot(session) as instance:
            result = await poll(instance, dispatcher(BackendClient(http, SECRET)), stop=stop)
    assert session.calls[0].offset is None
    if status == 200:
        assert result == 0 and session.calls[1].offset == 72
    else:
        assert result == 2 and len(session.calls) == 1
