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


@pytest.mark.parametrize("success_at", ["GigaChat-3-Lightning", "GigaChat-3-Pro", "GigaChat-3-Ultra", None])
@pytest.mark.parametrize("failure", ["outer_timeout", "bad_output", "unavailable"])
async def test_lightning_pro_ultra_order_and_shared_budget(monkeypatch, success_at, failure):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    models = ["GigaChat-3-Lightning", "GigaChat-3-Pro", "GigaChat-3-Ultra"]
    profiles = [LLMProfile(code=model, provider="gigachat", model=model) for model in models]

    async def complete(messages, schema, profile, *, timeout_s):
        calls.append((profile.model, timeout_s))
        clock[0] += timeout_s
        if profile.model == success_at:
            return {}, Usage(provider="gigachat", model=profile.model), "{}"
        if failure == "outer_timeout":
            raise TimeoutError
        raise ProviderError(failure, "controlled", usage=Usage(prompt_tokens=7, cost_rub=0.1))

    chain = ProviderChain(
        [SimpleNamespace(name="gigachat", complete_structured=complete)],
        append_mock=False,
        rate_limiter=SimpleNamespace(acquire=AsyncMock()),
    )
    chain.role_profiles = {"main": profiles[2], "twin": profiles[1], "duplicate": profiles[1]}
    if success_at is None:
        with pytest.raises(ProviderError):
            await chain.complete_structured([], {}, profiles[0], context="normalization", fallback_profile=profiles[2])
    else:
        result = await chain.complete_structured(
            [], {}, profiles[0], context="normalization", fallback_profile=profiles[2]
        )
        assert result.attempts[-1].model == success_at
        if failure != "outer_timeout":
            assert result.usage.prompt_tokens == (len(calls) - 1) * 7
    expected = list(zip(models, [4.0, 3.0, 3.0], strict=True))
    if success_at:
        expected = expected[: models.index(success_at) + 1]
    assert calls == expected
    assert clock[0] <= 10


@pytest.mark.parametrize("failure", ["auth", "quota", "rate_limit"])
async def test_pro_account_error_does_not_retry_ultra(failure):
    calls = []

    async def complete(messages, schema, profile, *, timeout_s):
        calls.append(profile.model)
        raise ProviderError("bad_output" if profile.model == "GigaChat-3-Lightning" else failure, "controlled")

    chain = ProviderChain(
        [SimpleNamespace(name="gigachat", complete_structured=complete)],
        append_mock=False,
        rate_limiter=SimpleNamespace(acquire=AsyncMock()),
    )
    chain.role_profiles = {"twin": LLMProfile(code="pro", provider="gigachat", model="GigaChat-3-Pro")}
    with pytest.raises(ProviderError, match="controlled"):
        await chain.complete_structured(
            [],
            {},
            LLMProfile(code="fast", provider="gigachat", model="GigaChat-3-Lightning"),
            context="normalization",
            fallback_profile=LLMProfile(code="main", provider="gigachat", model="GigaChat-3-Ultra"),
        )
    assert calls == ["GigaChat-3-Lightning", "GigaChat-3-Pro"]


async def test_unused_lightning_time_goes_to_pro_and_keeps_ultra_reserve(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock[0]))

    async def complete(messages, schema, profile, *, timeout_s):
        calls.append((profile.model, timeout_s))
        if profile.model == "GigaChat-3-Lightning":
            clock[0] += 1
            raise ProviderError("bad_output", "controlled")
        return {}, Usage(provider="gigachat", model=profile.model), "{}"

    chain = ProviderChain(
        [SimpleNamespace(name="gigachat", complete_structured=complete)],
        append_mock=False,
        rate_limiter=SimpleNamespace(acquire=AsyncMock()),
    )
    chain.role_profiles = {"twin": LLMProfile(code="pro", provider="gigachat", model="GigaChat-3-Pro")}
    await chain.complete_structured(
        [],
        {},
        LLMProfile(code="fast", provider="gigachat", model="GigaChat-3-Lightning"),
        context="normalization",
        fallback_profile=LLMProfile(code="main", provider="gigachat", model="GigaChat-3-Ultra"),
    )
    assert calls == [("GigaChat-3-Lightning", 4.0), ("GigaChat-3-Pro", 6.0)]
