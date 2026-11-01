"""Ограничения CLI проверяются на локальном MockTransport, реального egress нет."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm import live_smoke
from app.llm.openai_compat import DEFAULT_MODEL_IDS


def request(**updates):
    payload = {
        "model": DEFAULT_MODEL_IDS[0],
        "max_tokens": 128,
        "stream": False,
        "messages": [{"role": "user", "content": live_smoke.FIXED_TEXT}],
        **updates,
    }
    return httpx.Request("POST", live_smoke.BASE_URL + "/chat/completions", json=payload)


async def test_transport_caps_all_http_requests_including_key_queries():
    forwarded = []
    transport = live_smoke.BoundedTransport(
        httpx.MockTransport(lambda req: (forwarded.append(req), httpx.Response(200))[1])
    )
    try:
        await transport.handle_async_request(httpx.Request("GET", live_smoke.BASE_URL + "/key"))
        for _ in range(5):
            await transport.handle_async_request(request())
        with pytest.raises(httpx.RequestError, match="ограничениями"):
            await transport.handle_async_request(request())
        assert len(forwarded) == transport.requests == 6
    finally:
        await transport.aclose()


@pytest.mark.parametrize(
    "updates",
    [
        {"model": "unapproved/model"},
        {"max_tokens": 129},
        {"stream": True},
        {"messages": [{"role": "user", "content": "Пользовательский текст"}]},
    ],
)
async def test_transport_rejects_unapproved_payload_before_network(updates):
    inner = AsyncMock()
    transport = live_smoke.BoundedTransport(inner)
    with pytest.raises(httpx.RequestError):
        await transport.handle_async_request(request(**updates))
    inner.handle_async_request.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.test/api/v1/key",
        "https://openrouter.ai/api/v1/key?secret=1",
        "http://openrouter.ai/api/v1/key",
        "https://openrouter.ai/api/v1/other",
    ],
)
async def test_transport_rejects_other_destinations(url):
    inner = AsyncMock()
    transport = live_smoke.BoundedTransport(inner)
    with pytest.raises(httpx.RequestError):
        await transport.handle_async_request(httpx.Request("GET", url))
    inner.handle_async_request.assert_not_awaited()


async def test_cli_uses_sdk_three_fixed_models_and_never_reports_key_or_raw(monkeypatch):
    monkeypatch.setattr(
        live_smoke,
        "get_settings",
        lambda: SimpleNamespace(openrouter_api_key="synthetic-secret-key", openrouter_budget_usd=10, app_port=8000),
    )
    monkeypatch.setattr(live_smoke, "load_openrouter_budget", AsyncMock(return_value=10))
    monkeypatch.setattr(
        live_smoke,
        "deref",
        lambda name: {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    )
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage": 0, "limit_remaining": 10}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    monkeypatch.setattr(live_smoke.httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handler))
    status, report = await live_smoke.run()
    assert status == 0 and report["http_requests"] == 4
    assert [item["model"] for item in report["models"]] == list(DEFAULT_MODEL_IDS)
    assert "synthetic-secret-key" not in json.dumps(report) and "choices" not in json.dumps(report)
    assert len(seen) == 4
