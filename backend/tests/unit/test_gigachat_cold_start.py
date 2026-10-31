"""Холодный TLS, ротация ключей и отмена запроса не исчерпывают весь резерв."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider, generation_slot
from app.llm.keys import ApiKey, KeyPool

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def response(request):
    if request.url.path == "/oauth":
        return httpx.Response(
            200,
            json={
                "access_token": "token-" + request.headers["Authorization"][-1],
                "expires_at": (time.time() + 1800) * 1000,
            },
        )
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        },
    )


def provider(handler):
    return GigaChatProvider(
        KeyPool([ApiKey("one", "one"), ApiKey("two", "two")]),
        oauth_url="https://example.invalid/oauth",
        base_url="https://example.invalid",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("stage", ["oauth", "chat"])
@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
async def test_cold_transport_failure_rotates_key_within_budget(stage, error):
    failed = False
    calls = []

    def handler(request):
        nonlocal failed
        calls.append((request.url.path, request.headers["Authorization"]))
        assert request.extensions["timeout"]["connect"] <= 2.0
        if not failed and (request.url.path == "/oauth") == (stage == "oauth"):
            failed = True
            raise error("controlled", request=request)
        return response(request)

    p = provider(handler)
    try:
        obj, usage, _ = await p.complete_structured(
            [], SCHEMA, LLMProfile("fast", "gigachat", "GigaChat-3-Lightning"), timeout_s=4
        )
        assert obj == {"ok": True} and usage.key_label == "two"
        assert usage.request_count == 2 and usage.total_tokens == 8
        first = p.pool.keys[0]
        assert first.is_active and first.tokens_used == 0 and not first.available()
        assert p.pool.pick().label == "two"
        assert calls[-1] == ("/chat/completions", "Bearer token-o")
    finally:
        await p.aclose()


async def test_outer_model_timeout_rotates_key_for_pro_and_keeps_valid_token():
    calls = []

    async def handler(request):
        if request.url.path != "/oauth":
            model = json.loads(request.content)["model"]
            calls.append((model, request.headers["Authorization"]))
            if model == "GigaChat-3-Lightning":
                await asyncio.Event().wait()
        return response(request)

    p = provider(handler)
    chain = ProviderChain(
        [p], append_mock=False, timeouts={"normalization": 0.2}, rate_limiter=SimpleNamespace(acquire=AsyncMock())
    )
    chain.role_profiles = {"twin": LLMProfile("pro", "gigachat", "GigaChat-3-Pro")}
    try:
        result = await chain.complete_structured(
            [],
            SCHEMA,
            LLMProfile("fast", "gigachat", "GigaChat-3-Lightning"),
            context="normalization",
            fallback_profile=LLMProfile("main", "gigachat", "GigaChat-3-Ultra"),
        )
        assert [m for m, _ in calls] == ["GigaChat-3-Lightning", "GigaChat-3-Pro"]
        assert calls[0][1] != calls[1][1]
        assert result.usage.key_label == "two"
        assert not result.attempts[0].ok and result.attempts[1].ok
        assert p.pool.keys[0].access_token and p.pool.keys[0].is_active
        assert not p.pool.keys[0].available()
    finally:
        await p.aclose()


async def test_waiting_for_generation_slot_does_not_cool_down_healthy_key():
    p = provider(response)
    try:
        async with generation_slot(p.scope):
            with pytest.raises(ProviderError) as exc:
                await p.complete_structured(
                    [], SCHEMA, LLMProfile("fast", "gigachat", "GigaChat-3-Lightning"), timeout_s=0.02
                )
        assert exc.value.kind == "timeout"
        assert all(k.available() and k.last_error is None for k in p.pool.keys)
    finally:
        await p.aclose()


def test_transport_cooldown_expires_without_changing_quota_or_token(monkeypatch):
    import app.llm.keys as keys

    monkeypatch.setattr(keys, "time", SimpleNamespace(monotonic=lambda: 100.0))
    key = ApiKey("one", "one", access_token="cached", tokens_used=123)
    pool = KeyPool([key])
    pool.mark_error(key, ProviderError("timeout", "controlled"))
    assert key.cooldown_until == 110 and key.access_token == "cached" and key.tokens_used == 123 and key.is_active
    monkeypatch.setattr(keys, "time", SimpleNamespace(monotonic=lambda: 111.0))
    assert pool.pick() is key


def test_all_transport_cooling_keys_retry_oldest_but_never_429(monkeypatch):
    import app.llm.keys as keys

    monkeypatch.setattr(keys, "time", SimpleNamespace(monotonic=lambda: 100.0))
    a, b, c = ApiKey("one", "one"), ApiKey("two", "two"), ApiKey("limited", "limited")
    pool = KeyPool([a, b, c])
    pool.mark_error(a, ProviderError("timeout", "controlled"))
    monkeypatch.setattr(keys, "time", SimpleNamespace(monotonic=lambda: 101.0))
    pool.mark_error(b, ProviderError("network", "controlled"))
    pool.mark_error(c, ProviderError("rate_limit", "controlled", retry_after_s=60))
    assert pool.pick() is a
    assert pool.pick(exclude={a.label}) is b
    with pytest.raises(ProviderError) as exc:
        pool.pick(exclude={a.label, b.label})
    assert exc.value.kind == "rate_limit"
    pool.add_usage(a, 8)
    assert a.available() and a.last_error is None and a.cooldown_until == 0


async def test_backup_can_recover_when_every_key_had_transport_failure():
    failures = 2

    def handler(request):
        nonlocal failures
        if failures:
            failures -= 1
            raise httpx.ConnectTimeout("controlled", request=request)
        return response(request)

    p = provider(handler)
    chain = ProviderChain([p], append_mock=False, rate_limiter=SimpleNamespace(acquire=AsyncMock()))
    chain.role_profiles = {"twin": LLMProfile("pro", "gigachat", "GigaChat-3-Pro")}
    try:
        result = await chain.complete_structured(
            [],
            SCHEMA,
            LLMProfile("fast", "gigachat", "GigaChat-3-Lightning"),
            context="normalization",
            fallback_profile=LLMProfile("main", "gigachat", "GigaChat-3-Ultra"),
        )
        assert result.obj == {"ok": True}
        assert [a.model for a in result.attempts] == ["GigaChat-3-Lightning", "GigaChat-3-Pro"]
        assert result.usage.request_count == 3
        assert p.pool.keys[0].available()
    finally:
        await p.aclose()


def test_cancelled_parallel_request_cannot_override_retry_after(monkeypatch):
    import app.llm.keys as keys

    monkeypatch.setattr(keys, "time", SimpleNamespace(monotonic=lambda: 100.0))
    key = ApiKey("one", "one")
    pool = KeyPool([key])
    pool.mark_error(key, ProviderError("rate_limit", "controlled", retry_after_s=60))
    pool.mark_error(key, ProviderError("timeout", "cancelled"))
    assert key.cooldown_until == 160 and key.last_error.startswith("rate_limit:")
    with pytest.raises(ProviderError) as exc:
        pool.pick()
    assert exc.value.kind == "rate_limit"


async def test_prepare_rotates_cold_key_and_first_inference_reuses_oauth_and_api():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers["Authorization"]))
        if request.headers["Authorization"] == "Basic one":
            raise httpx.ConnectTimeout("controlled", request=request)
        if request.url.path == "/models":
            return httpx.Response(200, json={"data": []})
        return response(request)

    p = provider(handler)
    profile = LLMProfile("fast", "gigachat", "GigaChat-3-Lightning")
    try:
        assert await p.prepare([profile])
        assert p.pool.keys[1].access_token
        before = len(calls)
        obj, usage, _ = await p.complete_structured([], SCHEMA, profile, timeout_s=4)
        assert obj == {"ok": True} and usage.key_label == "two"
        assert calls[before:] == [("POST", "/chat/completions", "Bearer token-o")]
        assert not any(path == "/chat/completions" for _, path, _ in calls[:before])
    finally:
        await p.aclose()


async def test_prepare_no_live_role_does_not_contact_gigachat():
    p = provider(lambda request: pytest.fail("явный mock не делает сетевых запросов"))
    try:
        assert await p.prepare([LLMProfile("offline", "mock", "mock")])
    finally:
        await p.aclose()


async def test_prepare_unavailable_is_bounded_and_reports_failure():
    async def handler(request):
        await asyncio.Event().wait()

    p = provider(handler)
    try:
        assert not await p.prepare([LLMProfile("fast", "gigachat", "GigaChat-3-Lightning")], timeout_s=0.04)
        assert all(k.is_active and k.tokens_used == 0 for k in p.pool.keys)
    finally:
        await p.aclose()


async def test_prepare_second_pass_recovers_transport_failure_of_both_keys():
    failures = 2

    def handler(request):
        nonlocal failures
        if request.url.path == "/oauth" and failures:
            failures -= 1
            raise httpx.ConnectTimeout("controlled", request=request)
        if request.url.path == "/models":
            return httpx.Response(200, json={"data": []})
        return response(request)

    p = provider(handler)
    try:
        assert await p.prepare([LLMProfile("fast", "gigachat", "GigaChat-3-Lightning")])
        assert failures == 0
        assert all(k.access_token and k.is_active for k in p.pool.keys)
    finally:
        await p.aclose()
