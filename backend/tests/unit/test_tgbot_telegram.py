from __future__ import annotations

import asyncio
import logging
import traceback

import httpx
import pytest

from app.tgbot.telegram import DeliveryError, TelegramClient

TOKEN = "123456:" + "A" * 35
PAYLOAD = {"chat_id": 123, "text": "Synthetic text", "link_preview_options": {"is_disabled": True}}


async def test_send_uses_official_tls_origin_plain_text_and_validates_actual_identity(caplog):
    requests = []

    async def handle(request):
        requests.append(request)
        assert request.url.scheme == "https" and request.url.host == "api.telegram.org"
        logging.getLogger("httpcore.http11").debug("headers=%s", TOKEN)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42, "chat": {"id": 123}, "text": TOKEN}})

    client = TelegramClient(TOKEN, transport=httpx.MockTransport(handle))
    try:
        with caplog.at_level(logging.DEBUG):
            assert await client.send(PAYLOAD) == "telegram:42"
        assert len(requests) == 1
        assert TOKEN not in caplog.text
        assert "telegram_http_transport_event" in caplog.text
        assert b"parse_mode" not in requests[0].content
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "case,kind",
    [
        ("network", "unknown"),
        ("bad_json", "unknown"),
        ("oversize", "unknown"),
        ("server", "unknown"),
        ("forbidden", "rejected"),
        ("redirect", "unknown"),
        ("wrong_chat", "unknown"),
        ("boolean_id", "unknown"),
    ],
)
async def test_failure_never_retries_or_echoes_secret(case, kind, caplog):
    calls = []

    async def handle(request):
        calls.append(request)
        if case == "network":
            raise httpx.ReadTimeout(TOKEN, request=request)
        if case == "bad_json":
            return httpx.Response(200, text=TOKEN)
        if case == "oversize":
            return httpx.Response(200, text=TOKEN * 2000)
        if case == "server":
            return httpx.Response(503, json={"ok": False, "description": TOKEN})
        if case == "forbidden":
            return httpx.Response(403, json={"ok": False, "description": TOKEN})
        if case == "redirect":
            return httpx.Response(302, headers={"location": "https://other.invalid/" + TOKEN})
        return httpx.Response(
            200, json={"ok": True, "result": {"message_id": True if case == "boolean_id" else 42, "chat": {"id": 124}}}
        )

    client = TelegramClient(TOKEN, transport=httpx.MockTransport(handle))
    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(DeliveryError) as exc:
            await client.send(PAYLOAD)
        assert exc.value.kind == kind
        assert len(calls) == 1
        assert TOKEN not in "".join(traceback.format_exception(exc.value))
        assert TOKEN not in caplog.text
    finally:
        await client.aclose()


async def test_cancellation_propagates_and_does_not_trigger_retry():
    entered = asyncio.Event()
    calls = []

    async def handle(request):
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()

    client = TelegramClient(TOKEN, transport=httpx.MockTransport(handle))
    try:
        task = asyncio.create_task(client.send(PAYLOAD))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1
    finally:
        await client.aclose()


async def test_other_http_logging_context_is_preserved(caplog):
    client = TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("httpx").info("other_provider_safe_event")
        assert "other_provider_safe_event" in caplog.text
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {"chat_id": True, "text": "x"},
        {"chat_id": 123, "text": "😀" * 3000},
        {"chat_id": 123, "text": "x", "parse_mode": "HTML"},
    ],
)
async def test_invalid_payload_is_rejected_before_http(payload):
    calls = []

    async def handle(request):
        calls.append(request)
        raise AssertionError("unexpected HTTP")

    client = TelegramClient(TOKEN, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(DeliveryError) as exc:
            await client.send(payload)
        assert exc.value.kind == "rejected" and calls == []
    finally:
        await client.aclose()
