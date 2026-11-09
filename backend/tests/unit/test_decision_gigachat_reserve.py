"""Live classify/decide use configured Pro after invalid Ultra JSON; pinned/offline stays explicit."""

import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agent import nodes
from app.contracts.registry import deref, validate_schema
from app.llm.base import LLMProfile, ProviderError, Usage
from app.llm.failover import ChainResult, ProviderChain
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider

ULTRA = LLMProfile(code="decision-ultra", provider="gigachat", model="GigaChat-3-Ultra")
PRO = LLMProfile(code="decision-pro", provider="gigachat", model="GigaChat-3-Pro", role="twin")


@pytest.fixture
def prompt(monkeypatch):
    monkeypatch.setattr(
        nodes, "load_prompt", lambda *a: SimpleNamespace(body="Synthetic decision", render=lambda **k: "")
    )


@pytest.mark.parametrize("invalid_ultra,invalid_pro", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("task,schema_name", [("decide", "agent/decision"), ("classify", "agent/classification")])
async def test_actual_sdk_schema_repair_then_configured_pro_before_mock(
    prompt, invalid_ultra, invalid_pro, task, schema_name
):
    schema = deref(schema_name)
    valid, _, _ = await MockProvider().complete_structured(
        [{"role": "user", "content": "Вопрос по условиям карты"}], schema, ULTRA, timeout_s=1
    )
    assert validate_schema(valid, schema) == []
    calls = []

    def http(request):
        if request.url.path == "/oauth":
            return httpx.Response(
                200, json={"access_token": "synthetic-native-access", "expires_at": (time.time() + 3600) * 1000}
            )
        body = json.loads(request.content)
        calls.append((body["model"], request.extensions["timeout"]["read"]))
        invalid = invalid_ultra if body["model"] == ULTRA.model else invalid_pro
        obj = {**valid, "incident_link_incident_id": 1} if invalid else valid
        return httpx.Response(
            200,
            json={
                "model": body["model"] + ":synthetic",
                "choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    provider = GigaChatProvider(
        KeyPool([ApiKey("synthetic", "synthetic-decision-reserve")]),
        oauth_url="https://decision.invalid/oauth",
        base_url="https://decision.invalid/v1",
        transport=httpx.MockTransport(http),
    )
    mock = MockProvider()
    original = mock.complete_structured
    mock.complete_structured = AsyncMock(side_effect=original)
    chain = ProviderChain([provider, mock], append_mock=False)
    chain.role_profiles = {"main": ULTRA, "twin": PRO}
    try:
        obj, meta = await nodes._llm(SimpleNamespace(profile=ULTRA, chain=chain), task, schema_name, {}, "synthetic")
        assert validate_schema(obj, schema) == []
        expected = [ULTRA.model] * (2 if invalid_ultra else 1)
        if invalid_ultra:
            expected += [PRO.model] * (2 if invalid_pro else 1)
        assert [model for model, _ in calls] == expected
        assert all(0 < budget <= 30 for _, budget in calls)
        assert calls[-1][1] <= calls[0][1]
        if invalid_pro:
            assert meta["fallback_mock"] and meta["provider"] == "mock"
            assert mock.complete_structured.await_count == 1
        else:
            assert not meta["fallback_mock"] and meta["provider"] == "gigachat"
            assert meta["model"] == f"gigachat:{PRO.model if invalid_ultra else ULTRA.model}:synthetic"
            assert meta["usage"]["total_tokens"] == 5 * len(expected)
            mock.complete_structured.assert_not_awaited()
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "task,selector,offline,model,provider,configured,expected",
    [
        ("decide", None, None, ULTRA.model, "gigachat", True, True),
        ("classify", None, None, ULTRA.model, "gigachat", True, True),
        ("classify", "v1", None, ULTRA.model, "gigachat", True, False),
        ("classify", "v2", None, ULTRA.model, "gigachat", True, False),
        ("classify", None, "replay", ULTRA.model, "gigachat", True, False),
        ("classify", None, None, PRO.model, "gigachat", True, False),
        ("classify", None, None, ULTRA.model, "openai_compatible", True, False),
        ("classify", None, None, ULTRA.model, "gigachat", False, False),
        ("decide", "v1", None, ULTRA.model, "gigachat", True, False),
        ("decide", "v2", None, ULTRA.model, "gigachat", True, False),
        ("decide", None, "mock", ULTRA.model, "gigachat", True, False),
        ("decide", None, None, PRO.model, "gigachat", True, False),
        ("decide", None, None, ULTRA.model, "openai_compatible", True, False),
        ("decide", None, None, ULTRA.model, "gigachat", False, False),
    ],
)
async def test_reserve_keeps_pins_offline_other_tasks_and_existing_profile(
    prompt, task, selector, offline, model, provider, configured, expected
):
    primary = replace(
        ULTRA, model=model, provider=provider, extra={} if selector is None else {"agent_prompt_templates": selector}
    )
    reserve = replace(PRO, id=12, api_key_id=23, rpd_limit=7, temperature=0.2, extra={"request": {"max_tokens": 1024}})
    complete = AsyncMock(return_value=ChainResult({}, Usage(model=model), "{}", provider))
    chain = SimpleNamespace(
        names=[provider],
        offline_mode=offline,
        role_profiles={"twin": reserve} if configured else {},
        complete_structured=complete,
    )
    schema_name = "agent/classification" if task == "classify" else "agent/decision"
    await nodes._llm(SimpleNamespace(profile=primary, chain=chain), task, schema_name, {}, "synthetic")
    assert complete.call_args.kwargs.get("fallback_profile") is (reserve if expected else None)
    assert reserve.id == 12 and reserve.api_key_id == 23 and reserve.rpd_limit == 7 and reserve.role == "twin"
    assert reserve.extra == {"request": {"max_tokens": 1024}} and reserve.temperature == 0.2


@pytest.mark.parametrize("kind", ["auth", "quota", "rate_limit", "network", "timeout"])
@pytest.mark.parametrize("task,schema_name", [("decide", "agent/decision"), ("classify", "agent/classification")])
async def test_shared_failure_does_not_spend_pro_requests(prompt, kind, task, schema_name):
    complete = AsyncMock(side_effect=ProviderError(kind, "controlled"))
    provider = SimpleNamespace(name="gigachat", complete_structured=complete)
    chain = ProviderChain([provider])
    chain.role_profiles = {"twin": PRO}
    _, meta = await nodes._llm(SimpleNamespace(profile=ULTRA, chain=chain), task, schema_name, {}, "synthetic")
    assert meta["fallback_mock"] and complete.await_count == 1


async def test_explicit_reserve_is_not_replaced(prompt):
    explicit = replace(PRO, code="explicit")
    complete = AsyncMock(return_value=ChainResult({}, Usage(model=ULTRA.model), "{}", "gigachat"))
    chain = SimpleNamespace(names=["gigachat"], role_profiles={"twin": PRO}, complete_structured=complete)
    await nodes._llm(
        SimpleNamespace(profile=ULTRA, chain=chain),
        "decide",
        "agent/decision",
        {},
        "synthetic",
        fallback_profile=explicit,
    )
    assert complete.call_args.kwargs["fallback_profile"] is explicit


@pytest.mark.parametrize("task,schema_name", [("decide", "agent/decision"), ("classify", "agent/classification")])
async def test_decision_reserve_cannot_extend_original_deadline(prompt, monkeypatch, task, schema_name):
    from app.llm import failover

    clock = [0.0]
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    models = []

    async def complete(messages, schema, profile, *, timeout_s):
        models.append(profile.model)
        clock[0] += timeout_s
        raise ProviderError("bad_output", "controlled")

    chain = ProviderChain([SimpleNamespace(name="gigachat", complete_structured=complete)])
    chain.role_profiles = {"twin": PRO}
    _, meta = await nodes._llm(SimpleNamespace(profile=ULTRA, chain=chain), task, schema_name, {}, "synthetic")
    assert models == [ULTRA.model] and clock[0] == 30
    assert meta["fallback_mock"]
