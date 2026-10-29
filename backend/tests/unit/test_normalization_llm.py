"""Нормализация использует main LLM до mock, сохраняет диагностику и бюджет."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import random
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agent.nodes import Deps, normalize
from app.agent.state import new_state
from app.agent.tools.base import ToolContext
from app.contracts.registry import deref, validate
from app.llm.base import LLMProfile, ProviderError, Usage
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider, analyze
from app.llm.ratelimit import RateLimiter

FAST = LLMProfile(code="fast", provider="gigachat", model="GigaChat-3-Lightning", role="fast")
MAIN = LLMProfile(code="main", provider="gigachat", model="GigaChat-3-Ultra")
TEXT = "Не проходит оплата дебетовой картой, помогите разобраться."
SCHEMA = deref("agent/normalization")


class ModelProvider:
    name = "gigachat"

    def __init__(self, *, fail_main=False, error="bad_output", delay=0.0):
        self.fail_main, self.error, self.delay = fail_main, error, delay
        self.calls = []
        self.obj = MockProvider().fill(SCHEMA, analyze(TEXT), random.Random(0))
        self.obj.update(negativity=0, sentiment="positive", confidence=0)

    async def complete_structured(self, messages, schema, profile, *, timeout_s):
        self.calls.append((profile.model, timeout_s))
        if profile.model == FAST.model or self.fail_main:
            raise ProviderError(
                self.error,
                "некорректный structured output",
                usage=Usage(prompt_tokens=100, completion_tokens=10, provider=self.name, model=profile.model),
            )
        if self.delay:
            await asyncio.sleep(self.delay)
        return (
            self.obj,
            Usage(prompt_tokens=200, completion_tokens=20, provider=self.name, model=profile.model),
            json.dumps(self.obj),
        )


def chain(provider, **kwargs):
    return ProviderChain([provider], rate_limiter=RateLimiter(), **kwargs)


async def test_live_main_recovers_invalid_fast_output_and_accounts_both_calls():
    provider = ModelProvider()
    result = await chain(provider).complete_structured([], SCHEMA, FAST, fallback_profile=MAIN, context="fast_path")
    assert [model for model, _ in provider.calls] == [FAST.model, MAIN.model]
    assert result.provider == "gigachat" and result.usage.model == MAIN.model
    assert not result.fallback_mock and result.usage.source == "live"
    assert result.usage.prompt_tokens == 300 and result.usage.completion_tokens == 30
    assert result.usage.request_count == 2
    assert not result.usage.json_valid_first_try
    assert [a.model for a in result.attempts] == [FAST.model, MAIN.model]
    assert result.error and "bad_output" in result.error
    assert 0 < provider.calls[1][1] <= provider.calls[0][1] <= 8


async def test_both_models_invalid_keep_honest_mock_and_both_reasons():
    provider = ModelProvider(fail_main=True)
    result = await chain(provider).complete_structured([], SCHEMA, FAST, fallback_profile=MAIN)
    assert result.fallback_mock and result.usage.source == "mock"
    assert len(result.attempts) == 3
    assert [a.model for a in result.attempts[:2]] == [FAST.model, MAIN.model]
    assert all(not a.ok for a in result.attempts[:2])


@pytest.mark.parametrize("kind", ["auth", "quota", "rate_limit", "network"])
async def test_shared_provider_failure_does_not_retry_another_model(kind):
    provider = ModelProvider(error=kind)
    result = await chain(provider).complete_structured([], SCHEMA, FAST, fallback_profile=MAIN)
    assert result.fallback_mock
    assert len(provider.calls) == 1


async def test_fallback_obeys_shared_budget_including_main_request():
    provider = ModelProvider(delay=1)
    result = await chain(provider, timeouts={"fast_path": 0.25}).complete_structured(
        [], SCHEMA, FAST, fallback_profile=MAIN, context="fast_path"
    )
    assert result.fallback_mock and len(provider.calls) == 2
    assert provider.calls[1][1] <= provider.calls[0][1] <= 0.25
    assert "timeout" in result.attempts[1].error


async def test_explicit_mock_never_calls_live_main():
    provider = ModelProvider()
    result = await chain(provider).complete_structured(
        [], SCHEMA, dataclasses.replace(FAST, provider="mock"), fallback_profile=MAIN
    )
    assert result.provider == "mock" and not result.fallback_mock
    assert provider.calls == []


async def test_identical_main_model_is_not_requested_twice():
    provider = ModelProvider()
    result = await chain(provider).complete_structured(
        [], SCHEMA, FAST, fallback_profile=dataclasses.replace(FAST, code="main")
    )
    assert result.fallback_mock and len(provider.calls) == 1


async def test_main_can_use_another_configured_provider():
    fast, main = ModelProvider(), ModelProvider()
    main.name = "openai_compatible"
    selected = dataclasses.replace(MAIN, provider="openai_compatible", model="configured-main")
    result = await ProviderChain([fast, main], rate_limiter=RateLimiter()).complete_structured(
        [], SCHEMA, FAST, fallback_profile=selected
    )
    assert result.provider == "openai_compatible"
    assert [m for m, _ in main.calls] == ["configured-main"]


async def test_normalize_records_model_attempts_and_preserves_zero_values():
    conn = AsyncMock()
    provider = ModelProvider()
    deps = Deps(
        ToolContext(conn, run_id=1, agent_run_id=2, sim_time=dt.datetime(2026, 10, 29, tzinfo=dt.UTC)),
        chain(provider),
        MAIN,
        fast_profile=FAST,
    )
    state = new_state(1, {"id": 3, "channel": "chat", "text": TEXT}, 2, "v1.1")
    result = await normalize(state, deps)
    assert result["llm_source"] == "live"
    assert result["normalization"]["negativity"] == 0
    assert result["normalization"]["confidence"] == 0
    assert validate(result["normalization"], "agent/normalization") == []
    calls = [c.args for c in conn.execute.call_args_list if "insert into agent_steps" in c.args[0]]
    assert len(calls) == 1
    params = calls[0][1]
    assert params[3] == "ok" and params[10] == "gigachat:" + MAIN.model
    recorded = json.loads(params[4])
    assert [a["model"] for a in recorded["llm_attempts"]] == [FAST.model, MAIN.model]
    assert "bad_output" in recorded["fallback_reason"]
    assert "Причина резервирования" in params[8]


async def test_oauth_refresh_is_shared_by_concurrent_calls():
    requests = 0

    async def transport(request):
        nonlocal requests
        requests += 1
        await asyncio.sleep(0.01)
        return httpx.Response(
            200, json={"access_token": "synthetic-token", "expires_at": int((time.time() + 3600) * 1000)}
        )

    key = ApiKey("test", "synthetic-key")
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://provider.test/oauth",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(transport),
    )
    try:
        tokens = await asyncio.gather(*(provider._token(key, 1) for _ in range(8)))
        assert tokens == ["synthetic-token"] * 8
        assert requests == 1
    finally:
        await provider.aclose()


def test_temporarily_cooling_keys_are_not_reported_as_exhausted_quota():
    key = ApiKey("test", "synthetic-key", cooldown_until=time.monotonic() + 60)
    with pytest.raises(ProviderError) as error:
        KeyPool([key]).pick()
    assert error.value.kind == "rate_limit"
    assert error.value.retry_after_s > 0
    assert key.tokens_used == 0


async def test_explicit_replay_never_calls_live_main():
    from types import SimpleNamespace

    provider = ModelProvider()
    replay = SimpleNamespace(
        name="replay",
        complete_structured=AsyncMock(
            return_value=(
                provider.obj,
                Usage(provider="replay", model=FAST.model, source="replay"),
                json.dumps(provider.obj),
            )
        ),
    )
    result = await ProviderChain([provider, replay], rate_limiter=RateLimiter()).complete_structured(
        [], SCHEMA, dataclasses.replace(FAST, provider="replay"), fallback_profile=MAIN
    )
    assert result.provider == "replay" and result.usage.source == "replay"
    assert not result.fallback_mock and provider.calls == []


async def test_rate_limiter_wait_is_included_in_normalization_budget():
    from types import SimpleNamespace

    async def wait(*args):
        await asyncio.sleep(1)

    provider = ModelProvider()
    limiter = SimpleNamespace(acquire=AsyncMock(side_effect=wait))
    result = await ProviderChain([provider], rate_limiter=limiter, timeouts={"fast_path": 0.25}).complete_structured(
        [], SCHEMA, FAST, fallback_profile=MAIN, context="fast_path"
    )
    assert result.fallback_mock and provider.calls == []
    assert "timeout" in result.attempts[0].error
    limiter.acquire.assert_awaited_once()


async def test_queued_calls_do_not_repeat_oauth_after_first_429():
    requests = 0

    async def transport(request):
        nonlocal requests
        requests += 1
        await asyncio.sleep(0.01)
        return httpx.Response(429, text="synthetic rate limit", headers={"Retry-After": "20"})

    key = ApiKey("test", "synthetic-key")
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://provider.test/oauth",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(transport),
    )
    try:
        results = await asyncio.gather(
            *(provider.complete_structured([], SCHEMA, FAST, timeout_s=1) for _ in range(8)),
            return_exceptions=True,
        )
        assert all(isinstance(result, ProviderError) and result.kind == "rate_limit" for result in results)
        assert requests == 1 and key.tokens_used == 0
    finally:
        await provider.aclose()


async def test_invalid_gigachat_responses_keep_usage_cost_for_failover():
    def transport(request):
        if request.url.path == "/oauth":
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "expires_at": int((time.time() + 3600) * 1000)}
            )
        return httpx.Response(
            200,
            json={
                "model": MAIN.model,
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                "choices": [{"message": {"content": '{"invalid":true}'}}],
            },
        )

    profile = dataclasses.replace(MAIN, price_in_per_1m=10, price_out_per_1m=20)
    provider = GigaChatProvider(
        KeyPool([ApiKey("test", "synthetic-key")]),
        oauth_url="https://provider.test/oauth",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(transport),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured([], SCHEMA, profile, timeout_s=1)
        assert error.value.kind == "bad_output"
        usage = error.value.usage
        assert usage and usage.prompt_tokens == 4 and usage.completion_tokens == 6
        assert usage.cost_rub == pytest.approx(profile.cost(4, 6))
    finally:
        await provider.aclose()


async def test_provider_preserves_pool_cooldown_error():
    key = ApiKey("test", "synthetic-key", cooldown_until=time.monotonic() + 60)
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://provider.test/oauth",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured([], SCHEMA, FAST, timeout_s=1)
        assert error.value.kind == "rate_limit" and error.value.retry_after_s > 0
        assert error.value.usage and error.value.usage.request_count == 0
    finally:
        await provider.aclose()
