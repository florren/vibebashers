"""Нормализация резервирует время живой основной модели, общий дедлайн ограничен."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import nodes
from app.llm import failover
from app.llm.base import LLMProfile, ProviderError, Usage
from app.llm.failover import ProviderChain


@pytest.mark.parametrize("failure", ["outer_timeout", "timeout", "bad_output", "auth", "quota", "rate_limit"])
async def test_primary_budget_and_live_backup(monkeypatch, failure):
    clock = [0.0]
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    calls = []

    async def complete(messages, schema, profile, *, timeout_s):
        calls.append((profile.model, timeout_s))
        if profile.model == "fast":
            clock[0] += timeout_s
            if failure == "outer_timeout":
                raise TimeoutError
            raise ProviderError(failure, "controlled")
        clock[0] += 1
        return {"ok": True}, Usage(provider="gigachat", model="main"), "{}"

    provider = SimpleNamespace(name="gigachat", complete_structured=complete)
    chain = ProviderChain([provider], append_mock=False, rate_limiter=SimpleNamespace(acquire=AsyncMock()))
    fast = LLMProfile(code="fast", provider="gigachat", model="fast")
    main = LLMProfile(code="main", provider="gigachat", model="main")
    if failure in ("auth", "quota", "rate_limit"):
        with pytest.raises(ProviderError):
            await chain.complete_structured([], {}, fast, context="normalization", fallback_profile=main)
        assert calls == [("fast", 5.0)]
    else:
        result = await chain.complete_structured([], {}, fast, context="normalization", fallback_profile=main)
        assert result.provider == "gigachat" and result.usage.source == "live"
        assert calls == [("fast", 5.0), ("main", 5.0)]
        assert clock[0] == 6
    assert chain.timeout_for("fast_path") == 8
    assert chain.timeout_for("normalization") == 10


async def test_both_live_models_timeout_without_exceeding_total_budget(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock[0]))

    async def complete(messages, schema, profile, *, timeout_s):
        clock[0] += timeout_s
        raise TimeoutError

    chain = ProviderChain(
        [SimpleNamespace(name="gigachat", complete_structured=complete)],
        append_mock=False,
        rate_limiter=SimpleNamespace(acquire=AsyncMock()),
    )
    with pytest.raises(ProviderError):
        await chain.complete_structured(
            [],
            {},
            LLMProfile(code="fast", provider="gigachat", model="fast"),
            context="normalization",
            fallback_profile=LLMProfile(code="main", provider="gigachat", model="main"),
        )
    assert clock[0] == 10


async def test_normalize_uses_dedicated_context(monkeypatch):
    call = AsyncMock(
        return_value=(
            {
                "language": "ru",
                "summary_ru": "Вопрос",
                "negativity": 40,
                "sentiment": "neutral",
                "intents": ["question"],
                "confidence": 0.9,
            },
            {"provider": "gigachat", "model": "gigachat:fast"},
        )
    )
    monkeypatch.setattr(nodes, "_llm", call)
    deps = SimpleNamespace(
        fast_profile=LLMProfile(code="fast", provider="gigachat", model="fast"),
        profile=LLMProfile(code="main", provider="gigachat", model="main"),
        ctx=SimpleNamespace(conn=SimpleNamespace(execute=AsyncMock()), llm_source=None),
        record_step=AsyncMock(),
    )
    await nodes.normalize(
        {"signal": {"id": 1, "text": "Какая ставка по вкладу?", "channel": "chat"}, "errors": []}, deps
    )
    assert call.call_args.kwargs["context"] == "normalization"


@pytest.mark.parametrize("context,expected", [("fast_path", 8.0), ("default", 30.0)])
async def test_other_contexts_keep_timeout_policy(monkeypatch, context, expected):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock[0]))

    async def complete(messages, schema, profile, *, timeout_s):
        calls.append((profile.model, timeout_s))
        clock[0] += timeout_s
        raise TimeoutError

    chain = ProviderChain(
        [SimpleNamespace(name="gigachat", complete_structured=complete)],
        append_mock=False,
        rate_limiter=SimpleNamespace(acquire=AsyncMock()),
    )
    with pytest.raises(ProviderError):
        await chain.complete_structured(
            [],
            {},
            LLMProfile(code="fast", provider="gigachat", model="fast"),
            context=context,
            fallback_profile=LLMProfile(code="main", provider="gigachat", model="main"),
        )
    assert calls == [("fast", expected)]


async def test_without_different_live_backup_primary_gets_entire_budget():
    calls = []

    async def complete(messages, schema, profile, *, timeout_s):
        calls.append(timeout_s)
        return {}, Usage(provider="gigachat", model=profile.model), "{}"

    chain = ProviderChain(
        [SimpleNamespace(name="gigachat", complete_structured=complete)],
        append_mock=False,
        rate_limiter=SimpleNamespace(acquire=AsyncMock()),
    )
    profile = LLMProfile(code="one", provider="gigachat", model="one")
    await chain.complete_structured([], {}, profile, context="normalization", fallback_profile=profile)
    assert calls == [10.0]
