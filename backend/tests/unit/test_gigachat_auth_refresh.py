"""OAuth после простоя не отнимает короткий бюджет благодарности (SIG-000809/810)."""

import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm.base import LLMProfile, ProviderError
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool

PROFILE = LLMProfile("live", "gigachat", "GigaChat-3-Lightning")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def provider(handler, *, expires_in=100):
    key = ApiKey("test", "synthetic", access_token="old", token_expires_at=time.time() + expires_in)
    return GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://example.invalid/oauth",
        base_url="https://example.invalid",
        transport=httpx.MockTransport(handler),
    )


def response(request):
    if request.url.path == "/oauth":
        return httpx.Response(200, json={"access_token": "new", "expires_at": (time.time() + 1800) * 1000})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        },
    )


async def test_valid_cache_serves_generation_while_background_oauth_is_slow():
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(request):
        calls.append((request.url.path, request.headers["Authorization"]))
        if request.url.path == "/oauth":
            assert request.extensions["timeout"]["connect"] == 12
            entered.set()
            await finish.wait()
        return response(request)

    p = provider(handler)
    refresh = asyncio.create_task(p.refresh_auth())
    try:
        await entered.wait()
        obj, usage, _ = await asyncio.wait_for(p.complete_structured([], SCHEMA, PROFILE, timeout_s=0.1), 0.2)
        assert obj == {"ok": True} and usage.source == "live"
        assert ("/chat/completions", "Bearer old") in calls
        finish.set()
        await refresh
        assert p.pool.keys[0].access_token == "new"
        assert p.pool.keys[0].tokens_used == 4  # Только генерация, не OAuth.
        await p.complete_structured([], SCHEMA, PROFILE, timeout_s=0.1)
        assert calls[-1] == ("/chat/completions", "Bearer new")
        assert sum(path == "/oauth" for path, _ in calls) == 1
    finally:
        finish.set()
        await refresh
        await p.aclose()


async def test_concurrent_refreshes_do_not_duplicate_oauth():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return response(request)

    p = provider(handler)
    try:
        await asyncio.gather(p.refresh_auth(), p.refresh_auth())
        assert calls == ["/oauth"]
        assert p.pool.keys[0].requests_today == 0 and p.pool.keys[0].tokens_used == 0
    finally:
        await p.aclose()


@pytest.mark.parametrize("failure", ["deadline", "network", "bad_json"])
async def test_transient_refresh_failure_keeps_working_token_available(failure):
    async def handler(request):
        if request.url.path == "/oauth":
            if failure == "deadline":
                await asyncio.Event().wait()
            if failure == "network":
                raise httpx.ConnectError("controlled", request=request)
            return httpx.Response(200, text="invalid json")
        return response(request)

    p = provider(handler)
    try:
        await p.refresh_auth(timeout_s=0.02)
        key = p.pool.keys[0]
        assert key.access_token == "old" and key.available() and key.is_active
        assert key.last_error is None and key.cooldown_until == 0
        obj, usage, _ = await p.complete_structured([], SCHEMA, PROFILE, timeout_s=0.1)
        assert obj == {"ok": True} and usage.source == "live"
    finally:
        await p.aclose()


@pytest.mark.parametrize("status", [401, 429])
async def test_background_refresh_respects_auth_and_rate_limit(status):
    p = provider(lambda request: httpx.Response(status, text="controlled", headers={"Retry-After": "20"}))
    try:
        await p.refresh_auth()
        key = p.pool.keys[0]
        assert not key.available()
        if status == 401:
            assert not key.is_active and key.access_token is None
        else:
            assert key.access_token == "old"
            with pytest.raises(ProviderError) as exc:
                await p._token(key, 1)
            assert exc.value.kind == "rate_limit"
    finally:
        await p.aclose()


async def test_fresh_and_disabled_keys_do_not_refresh():
    calls = []
    p = provider(lambda request: calls.append(request), expires_in=1800)
    try:
        await p.refresh_auth()
        p.pool.keys[0].token_expires_at = time.time() + 100
        p.pool.keys[0].is_active = False
        await p.refresh_auth()
        assert calls == []
    finally:
        await p.aclose()


async def test_prepare_starts_one_auth_worker_and_close_cancels_it():
    p = provider(response, expires_in=1800)
    try:
        assert await p.prepare([PROFILE])
        task = p._auth_task
        assert task is not None
        assert await p.prepare([PROFILE])
        assert p._auth_task is task
    finally:
        await p.aclose()
    assert task.cancelled() and p._client.is_closed


async def test_offline_prepare_never_starts_auth_worker():
    p = provider(lambda request: pytest.fail("offline OAuth request"))
    try:
        assert await p.prepare([LLMProfile("offline", "mock", "mock")])
        assert p._auth_task is None
    finally:
        await p.aclose()


async def test_auth_worker_retries_after_unexpected_error(monkeypatch):
    p = provider(response)
    sleeper = AsyncMock()
    monkeypatch.setattr("app.llm.gigachat.asyncio.sleep", sleeper)
    p.refresh_auth = AsyncMock(side_effect=[RuntimeError("controlled"), asyncio.CancelledError()])
    try:
        with pytest.raises(asyncio.CancelledError):
            await p._auth_loop()
        assert p.refresh_auth.await_count == 2
    finally:
        await p.aclose()


async def test_stopping_auth_worker_preserves_client_for_inflight_generation():
    p = provider(response, expires_in=1800)
    try:
        await p.prepare([PROFILE])
        task = p._auth_task
        await p.stop_auth_refresh()
        assert task is not None and task.cancelled() and not p._client.is_closed
        obj, _, _ = await p.complete_structured([], SCHEMA, PROFILE, timeout_s=0.1)
        assert obj == {"ok": True}
    finally:
        await p.aclose()


async def test_backend_shutdown_closes_auth_worker(monkeypatch):
    from types import SimpleNamespace

    from app.config import get_settings
    from app.main import lifespan

    p = provider(response, expires_in=1800)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    monkeypatch.setattr("app.main.build_chain", lambda settings: SimpleNamespace(providers=[p], names=["gigachat"]))
    monkeypatch.setattr("app.main.bridge.stop", AsyncMock())
    try:
        async with lifespan(SimpleNamespace(state=SimpleNamespace())):
            await p.prepare([PROFILE])
            task = p._auth_task
        assert task is not None and task.cancelled() and p._client.is_closed
    finally:
        await p.aclose()
        get_settings.cache_clear()


async def test_runtime_chain_switch_stops_old_worker_and_prepares_new_one(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.api.envfile import apply_runtime

    old, new = provider(response, expires_in=1800), provider(response, expires_in=1800)
    await old.prepare([PROFILE])
    old_task = old._auth_task
    chain = SimpleNamespace(providers=[new], role_profiles={"main": PROFILE}, names=["gigachat"])
    app = SimpleNamespace(state=SimpleNamespace(llm_chain=SimpleNamespace(providers=[old])))
    monkeypatch.setattr("app.api.envfile.get_settings", Mock(return_value=SimpleNamespace(is_test=False)))
    monkeypatch.setattr("app.llm.failover.build_chain", lambda settings: chain)
    monkeypatch.setattr("app.llm.failover.default_profile", lambda settings: PROFILE)
    monkeypatch.setattr("app.llm.roles.refresh", AsyncMock())
    try:
        await apply_runtime(app, {})
        assert old_task is not None and old_task.cancelled() and not old._client.is_closed
        assert app.state.llm_chain is chain and new._auth_task is not None
    finally:
        await old.aclose()
        await new.aclose()
