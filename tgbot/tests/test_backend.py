from __future__ import annotations

import json
import traceback

import httpx
import pytest
from app.tgbot.signature import verify_signature

from cx_tgbot.backend import BackendClient, BackendUnavailable

SECRET = b"public-test-vector-only-000000000000"


async def test_wire_is_verified_by_actual_backend_and_preserves_utf8():
    calls = []

    async def handle(request):
        verify_signature(
            SECRET,
            method=request.method,
            path=request.url.path,
            body=request.content,
            timestamp=request.headers["X-CX-Tg-Timestamp"],
            signature=request.headers["X-CX-Tg-Signature"],
        )
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"reply_text": "Принято"})

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        event = {"chat_id": 123, "kind": "start", "text": "проверка"}
        assert await BackendClient(http, SECRET).submit(event) == {"reply_text": "Принято"}
    assert calls == [event]


@pytest.mark.parametrize("kind", ["network", "http", "invalid_json", "wrong_type"])
async def test_upstream_errors_never_echo_response_or_exception(kind):
    marker = "synthetic-private-upstream-echo"

    async def handle(request):
        if kind == "network":
            raise httpx.ConnectError(marker, request=request)
        if kind == "http":
            return httpx.Response(500, text=marker)
        if kind == "invalid_json":
            return httpx.Response(200, text=marker)
        return httpx.Response(200, json=[marker])

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(BackendUnavailable) as exc:
            await BackendClient(http, SECRET).submit({"chat_id": 123})
    assert marker not in "".join(traceback.format_exception(exc.value))
    assert str(exc.value) == "telegram_backend_unavailable"


async def test_oversized_update_fails_before_http():
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(base_url="http://backend.test", transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ValueError, match="^telegram_update_too_large$"):
            await BackendClient(http, SECRET).submit({"text": "я" * 20_000})
    assert calls == []


def test_missing_service_secret_fails_before_http():
    with pytest.raises(ValueError, match="^telegram_internal_secret_too_short$"):
        BackendClient(httpx.AsyncClient(), b"")
