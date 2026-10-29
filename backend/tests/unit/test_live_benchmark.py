"""Регрессии полного живого benchmark без обращений к внешнему API."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.bench.runner import load_dataset, run
from app.bench.service import BenchService
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider, generation_slot
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider


def test_benchmark_normalizes_temperature_without_changing_twin_profile():
    row = {
        "code": "gigachat_pro",
        "provider": "gigachat",
        "model": "GigaChat-3-Pro",
        "role": "twin",
        "temperature": 0.7,
    }
    profile = BenchService.profile(row)
    assert profile.temperature == 0
    assert row["temperature"] == 0.7


@pytest.mark.parametrize("model", ["GigaChat-3-Pro", "GigaChat-3-Ultra", "GigaChat-3-Lightning"])
async def test_native_json_repair_is_counted_and_key_usage_not_doubled(model):
    calls = []

    async def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "synthetic", "expires_at": 9999999999999})
        calls.append(json.loads(request.content))
        content = "{}" if len(calls) == 1 else '{"ok":true}'
        return httpx.Response(
            200,
            json={
                "model": model + ":synthetic",
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    key = ApiKey("synthetic", "synthetic")
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://test.invalid/oauth",
        base_url="https://test.invalid",
        transport=httpx.MockTransport(handler),
    )
    profile = LLMProfile(
        code="test",
        provider="gigachat",
        model=model,
        temperature=0,
        extra={"request": {"temperature": 0.7, "model": "wrong", "stream": True}},
    )
    try:
        obj, usage, _ = await provider.complete_structured(
            [{"role": "user", "content": "Синтетическая проверка"}],
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            profile,
            timeout_s=5,
        )
        assert obj == {"ok": True}
        assert all(
            ("НЕ шаблон ответа" in call["messages"][0]["content"]) == (model == "GigaChat-3-Lightning")
            for call in calls
        )
        assert usage.request_count == 2 and usage.structured_retries == 1
        assert usage.json_valid_first_try is False
        assert usage.total_tokens == 30 and key.tokens_used == 30
        assert all(call["temperature"] == 0 and call["model"] == model and call["stream"] is False for call in calls)
    finally:
        await provider.aclose()


async def test_bad_json_case_is_measured_and_remaining_cases_are_processed():
    class BadFirst(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def complete_structured(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("bad_output", "synthetic")
            return await super().complete_structured(*args, **kwargs)

    provider = BadFirst()
    record = await run(
        "lite_v1",
        LLMProfile(code="mock", provider="mock", model="mock"),
        cases=load_dataset("lite_v1")[:3],
        chain=ProviderChain([provider], append_mock=False),
    )
    assert record.status == "done" and len(record.results) == 3 and provider.calls == 3
    assert record.metrics["failed_cases"] == 1 and record.metrics["tool_success_rate"] == pytest.approx(2 / 3)
    assert record.metrics["complete"] is True
    assert all(value is False for value in record.results[0]["correct"].values())
    assert record.results[0]["fallback_mock"] is False


@pytest.mark.parametrize("kind", ["auth", "quota", "rate_limit"])
async def test_quota_and_auth_errors_stop_without_spending_other_cases(kind):
    class Stop(MockProvider):
        calls = 0

        async def complete_structured(self, *args, **kwargs):
            self.calls += 1
            raise ProviderError(kind, "synthetic")

    provider = Stop()
    record = await run(
        "lite_v1",
        LLMProfile(code="mock", provider="mock", model="mock"),
        cases=load_dataset("lite_v1")[:3],
        chain=ProviderChain([provider], append_mock=False),
    )
    assert record.status == "failed" and provider.calls == 1 and record.results == []
    assert kind in record.error


async def test_pers_stream_limit_is_shared_across_clients_and_profiles():
    inflight = 0
    peak = 0

    async def request():
        nonlocal inflight, peak
        async with generation_slot("GIGACHAT_API_PERS"):
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.01)
            inflight -= 1

    await asyncio.gather(*(request() for _ in range(4)))
    assert peak == 1


async def test_transport_outage_is_bounded_and_partial_metrics_are_marked():
    class Offline(MockProvider):
        calls = 0

        async def complete_structured(self, *args, **kwargs):
            self.calls += 1
            raise ProviderError("network", "synthetic")

    provider = Offline()
    record = await run(
        "lite_v1",
        LLMProfile(code="mock", provider="mock", model="mock"),
        cases=load_dataset("lite_v1")[:5],
        chain=ProviderChain([provider], append_mock=False),
    )
    assert record.status == "failed" and len(record.results) == 3 and provider.calls == 3
    assert record.metrics["complete"] is False
    assert record.metrics["evaluated_cases"] == 3 and record.metrics["expected_cases"] == 5


async def test_failed_native_json_keeps_usage_and_evaluates_all_cases():
    async def handler(request):
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "synthetic", "expires_at": 9999999999999})
        return httpx.Response(
            200,
            json={
                "model": "GigaChat-3-Lightning:synthetic",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    key = ApiKey("synthetic", "synthetic")
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://test.invalid/oauth",
        base_url="https://test.invalid",
        transport=httpx.MockTransport(handler),
    )
    try:
        profile = LLMProfile(code="test-failed", provider="gigachat", model="GigaChat-3-Lightning")
        record = await run(
            "lite_v1", profile, cases=load_dataset("lite_v1")[:2], chain=ProviderChain([provider], append_mock=False)
        )
        assert record.status == "done" and record.metrics["complete"]
        assert record.metrics["failed_cases"] == 2 and record.metrics["tool_success_rate"] == 0
        assert record.metrics["requests_total"] == 4 and record.metrics["tokens_total"] == 60
        assert record.metrics["retries_avg"] == 1 and record.metrics["json_valid_rate"] == 0
        assert key.tokens_used == 60
        assert all(r["predicted"]["_benchmark_error"]["kind"] == "bad_output" for r in record.results)
    finally:
        await provider.aclose()
