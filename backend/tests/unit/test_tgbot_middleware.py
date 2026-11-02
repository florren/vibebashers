from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from app.tgbot.middleware import INBOUND_PATH, BotSignatureMiddleware

SECRET = b"public-test-vector-only-000000000000"


def signed(body):
    stamp = str(int(time.time()))
    payload = "\n".join(("cx-tgbot-v1", stamp, "POST", INBOUND_PATH, hashlib.sha256(body).hexdigest())).encode()
    return [
        (b"x-cx-tg-timestamp", stamp.encode()),
        (b"x-cx-tg-signature", hmac.new(SECRET, payload, hashlib.sha256).hexdigest().encode()),
    ]


async def invoke(*, body=b"{}", headers=None, secret=SECRET, path=INBOUND_PATH, events=None):
    calls, sent = [], []
    queue = iter(events or [{"type": "http.request", "body": body}])

    async def receive():
        return next(queue)

    async def app(scope, receive, send):
        calls.append(await receive())

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "method": "POST", "headers": signed(body) if headers is None else headers}
    await BotSignatureMiddleware(app, lambda: secret)(scope, receive, send)
    return calls, sent


async def test_exact_utf8_chunks_reach_handler_once_after_verification():
    body = '{"text":"Проверка"}'.encode()
    events = [
        {"type": "http.request", "body": body[:5], "more_body": True},
        {"type": "http.request", "body": body[5:]},
    ]
    calls, sent = await invoke(body=body, events=events)
    assert calls == [{"type": "http.request", "body": body, "more_body": False}]
    assert sent == []


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"x-cx-tg-timestamp", b"0")],
        signed(b"{}") * 2,
        [(b"x-cx-tg-timestamp", b"\xff"), (b"x-cx-tg-signature", b"a" * 64)],
    ],
)
async def test_invalid_headers_never_call_handler(headers):
    calls, sent = await invoke(headers=headers)
    assert calls == [] and sent[0]["status"] == 401


async def test_tampered_body_never_calls_handler():
    calls, sent = await invoke(body=b'{"changed":true}', headers=signed(b"{}"))
    assert calls == [] and sent[0]["status"] == 401


async def test_disabled_transport_does_not_consume_body_or_call_handler():
    calls, sent = await invoke(secret=None, events=[{"type": "unexpected_if_consumed"}])
    assert calls == [] and sent[0]["status"] == 503


async def test_actual_size_limit_stops_before_reading_remaining_chunks():
    calls, sent = await invoke(events=[{"type": "http.request", "body": b"x" * 32769, "more_body": True}])
    assert calls == [] and sent[0]["status"] == 413


async def test_disconnect_does_not_reach_handler_or_send_response():
    assert await invoke(events=[{"type": "http.disconnect"}]) == ([], [])


async def test_other_routes_preserve_existing_behavior():
    calls, sent = await invoke(path="/api/public/claim", headers=[])
    assert calls == [{"type": "http.request", "body": b"{}"}] and sent == []
