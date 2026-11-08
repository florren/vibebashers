"""Bounded recorder проверяется фиктивным HTTP, без ключей и внешней сети."""

import json
from dataclasses import replace

import httpx
import pytest

from app.llm.base import LLMProfile, ProviderError
from app.replay.scenario11_record import BASE, LIMITS, MODEL, OAUTH, BoundedTransport, manifest, recording_profile


@pytest.fixture
def boundary():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = BoundedTransport(httpx.MockTransport(handler), secret="synthetic-private-marker")
    transport.arm([{"role": "user", "content": "Синтетический вопрос"}], {"type": "object"})
    return transport, calls


def payload(transport):
    return {"model": MODEL, "messages": transport.expected, "temperature": 0, "stream": False, "max_tokens": 1024}


async def send(transport, body):
    return await transport.handle_async_request(httpx.Request("POST", BASE + "/chat/completions", json=body))


async def test_initial_and_only_schema_correction_allowed(boundary):
    transport, calls = boundary
    body = payload(transport)
    await send(transport, body)
    body["messages"] = [
        *body["messages"],
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": "Ответ не прошёл валидацию по схеме: missing. Верни исправленный JSON целиком."},
    ]
    await send(transport, body)
    with pytest.raises(ProviderError, match="bounded_inference_limit"):
        await send(transport, body)
    assert len(calls) == 2 and transport.counts["inference"] == 2


@pytest.mark.parametrize(
    "change", ["model", "max_tokens", "stream", "messages", "extra", "bytes", "secret", "temperature"]
)
async def test_unreviewed_payload_never_reaches_http(boundary, change):
    transport, calls = boundary
    body = payload(transport)
    if change == "model":
        body["model"] = "unapproved"
    elif change == "max_tokens":
        body["max_tokens"] = 1025
    elif change == "stream":
        body["stream"] = True
    elif change == "extra":
        body["tools"] = []
    elif change == "temperature":
        body["temperature"] = 0.5
    else:
        text = {"messages": "Changed", "bytes": "x" * 70000, "secret": "synthetic-private-marker"}[change]
        if change == "secret":
            transport.arm([{"role": "user", "content": text}], {"type": "object"})
            body = payload(transport)
        else:
            body["messages"] = [{"role": "user", "content": text}]
    with pytest.raises(ProviderError):
        await send(transport, body)
    assert not calls


async def test_endpoint_oauth_scope_and_repeat_guard(boundary):
    transport, calls = boundary
    for url in [BASE + "/models?unreviewed=1", "https://other.invalid/chat/completions"]:
        with pytest.raises(ProviderError):
            await transport.handle_async_request(httpx.Request("GET", url))
    with pytest.raises(ProviderError):
        await transport.handle_async_request(httpx.Request("POST", OAUTH, content=b"scope=WRONG"))
    await transport.handle_async_request(httpx.Request("POST", OAUTH, content=b"scope=GIGACHAT_API_PERS"))
    with pytest.raises(ProviderError):
        await transport.handle_async_request(httpx.Request("POST", OAUTH, content=b"scope=GIGACHAT_API_PERS"))
    assert len(calls) == 1


async def test_all_http_and_balance_limits(boundary):
    transport, calls = boundary
    for _ in range(6):
        await transport.handle_async_request(httpx.Request("GET", BASE + "/balance"))
    with pytest.raises(ProviderError):
        await transport.handle_async_request(httpx.Request("GET", BASE + "/balance"))
    assert len(calls) == 6


async def test_upstream_failure_halts_and_redacts():
    transport = BoundedTransport(
        httpx.MockTransport(lambda r: httpx.Response(500, text="synthetic-secret")), secret="synthetic-secret"
    )
    response = await transport.handle_async_request(httpx.Request("GET", BASE + "/balance"))
    assert "synthetic-secret" not in response.text
    with pytest.raises(ProviderError):
        await transport.handle_async_request(httpx.Request("GET", BASE + "/balance"))


def test_manifest_exact_synthetic_and_no_dynamic_hash_claim():
    plan = manifest()
    assert plan["credential_slot"] == "gigachat1" and plan["limits"] == LIMITS
    assert len(plan["schema_sha256"]) == 3
    assert plan["primary_bank_read_write"] is False
    assert "NOT live hashes" in plan["request_dependency"]
    json.dumps(plan)


def test_generation_profile_keeps_budget_and_binding():
    original = LLMProfile(
        code="existing",
        provider="gigachat",
        model=MODEL,
        rpd_limit=20,
        rpm_limit=3,
        id=7,
        temperature=0.7,
        extra={"json_schema": True},
    )
    result = recording_profile(original)
    assert result.id == 7 and result.rpd_limit == 20 and result.rpm_limit == 3
    assert result.extra["structured_attempts"] == 2 and result.extra["agent_prompt_templates"] == "v2"
    assert original.extra == {"json_schema": True}
    assert result.temperature == 0.0
    with pytest.raises(ValueError):
        recording_profile(replace(original, model="unreviewed"))


@pytest.mark.parametrize(
    "names,selector,task,expected",
    [
        (["replay"], None, "normalize", "v1"),
        (["gigachat"], None, "normalize", "v2"),
        (["replay"], "v2", "normalize", "v2"),
        (["replay"], "v2", "classify", "v2"),
        (["gigachat"], "v1", "classify", "v1"),
        (["replay"], "v2", "decide", "v1"),
        (["gigachat"], None, "decide", "v3"),
        (["replay"], None, "decide", "v1"),
        (["gigachat"], "v1", "decide", "v1"),
    ],
)
async def test_template_opt_in_retains_old_defaults(monkeypatch, names, selector, task, expected):
    from types import SimpleNamespace

    from app.agent import nodes
    from app.llm.base import Usage
    from app.llm.failover import ChainResult

    seen = []

    def load(task, version="v1"):
        seen.append((task, version))
        return SimpleNamespace(body="system", render=lambda **kw: version)

    async def complete(*args, **kw):
        return ChainResult(obj={}, usage=Usage(model=MODEL), raw="{}", provider="replay")

    monkeypatch.setattr(nodes, "load_prompt", load)
    profile = LLMProfile(
        code="t",
        provider="gigachat",
        model=MODEL,
        extra={} if selector is None else {"agent_prompt_templates": selector},
    )
    deps = SimpleNamespace(profile=profile, chain=SimpleNamespace(names=names, complete_structured=complete))
    await nodes._llm(deps, task, "agent/normalization", {}, "synthetic")
    assert (task, expected) in seen


async def test_unknown_template_refused_before_provider(monkeypatch):
    from types import SimpleNamespace

    from app.agent import nodes

    called = []

    async def complete(*a, **kw):
        called.append(True)

    profile = LLMProfile(code="t", provider="gigachat", model=MODEL, extra={"agent_prompt_templates": "v99"})
    deps = SimpleNamespace(profile=profile, chain=SimpleNamespace(names=["replay"], complete_structured=complete))
    with pytest.raises(ValueError, match="agent_prompt_templates"):
        await nodes._llm(deps, "normalize", "agent/normalization", {}, "synthetic")
    assert not called


def test_live_decide_omits_computed_sla_without_relaxing_schema():
    from app.agent.prompts import load
    from app.contracts.registry import deref, validate_schema

    schema = deref("agent/decision")
    assert "sla" not in schema["required"]
    assert schema["properties"]["sla"]["type"] == "object"
    assert any("sla" in error for error in validate_schema({"sla": None}, schema))
    assert "Поле sla не передавай" in load("decide", "v3").body
    assert "Поле sla не передавай" not in load("decide", "v1").body


@pytest.mark.parametrize("failure", ["transport", "durable", "slot", "binding", "temperature"])
async def test_record_preflight_refuses_before_staging_or_http(boundary, tmp_path, failure):
    from types import SimpleNamespace

    from app.replay.scenario11_record import record

    transport, calls = boundary
    profile = LLMProfile(code="t", provider="gigachat", model=MODEL)
    provider = SimpleNamespace(
        _client=SimpleNamespace(_transport=transport),
        accounting=SimpleNamespace(durable=True),
        pool=SimpleNamespace(keys=[SimpleNamespace(label="gigachat_env_1")]),
    )
    if failure == "transport":
        provider._client._transport = object()
    elif failure == "durable":
        provider.accounting.durable = False
    elif failure == "slot":
        provider.pool.keys[0].label = "gigachat_env_2"
    elif failure == "binding":
        profile.api_key_id = 3
    else:
        profile.temperature = 0.3
    with pytest.raises(ValueError):
        await record(None, provider, transport, profile, tmp_path / "stage")
    assert not calls and not (tmp_path / "stage").exists()


async def test_live_cli_requires_separate_review_before_any_connection(tmp_path):
    from argparse import Namespace

    from scripts.replay11_record import execute

    private = tmp_path / "private.json"
    private.write_text(json.dumps({"dsn": "postgresql://synthetic:unused@no-network.invalid/cx_replay11_unused"}))
    args = Namespace(
        action="live",
        bank_dsn_file=private,
        output=tmp_path / "output",
        plan=None,
        approved_plan_sha256=None,
        profile_id=None,
    )
    with pytest.raises(ValueError, match="reviewed_plan_and_profile_required"):
        await execute(args)
    args.plan = tmp_path / "plan.json"
    args.plan.write_text(json.dumps({"manifest": {}}))
    args.approved_plan_sha256 = "invalid"
    args.profile_id = 1
    with pytest.raises(ValueError, match="reviewed_plan_changed"):
        await execute(args)
    assert not args.output.exists()


async def test_cold_oauth_uses_proactive_budget_once_and_graph_reuses_cache():
    """RED: cold connect needs >2s; GREEN: public startup warms both hosts with12s budget."""
    import time

    from scripts.replay11_record import warm_recording_provider

    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool
    from app.replay.scenario11_record import BoundedTransport

    async def handler(request):
        if request.extensions["timeout"]["connect"] <= 2:
            raise httpx.ConnectTimeout("synthetic cold TLS needs >2s", request=request)
        if str(request.url) == BASE + "/models":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(
            200, json={"access_token": "synthetic-warmed-token", "expires_at": int((time.time() + 3600) * 1000)}
        )

    old_transport = BoundedTransport(httpx.MockTransport(handler), secret="synthetic-auth")
    old = GigaChatProvider(
        KeyPool([ApiKey("fake", "synthetic-auth")]), oauth_url=OAUTH, base_url=BASE, transport=old_transport
    )
    try:
        with pytest.raises(ProviderError, match="oauth: ConnectTimeout"):
            await old._token(old.pool.keys[0], timeout_s=10)
        assert old_transport.counts == {"oauth": 1, "models": 0, "balance": 0, "inference": 0}
    finally:
        await old.aclose()
    fresh_transport = BoundedTransport(httpx.MockTransport(handler), secret="synthetic-auth")
    fresh = GigaChatProvider(
        KeyPool([ApiKey("fake", "synthetic-auth")]), oauth_url=OAUTH, base_url=BASE, transport=fresh_transport
    )
    try:
        await warm_recording_provider(fresh, LLMProfile(code="t", provider="gigachat", model=MODEL))
        assert await fresh._token(fresh.pool.keys[0], timeout_s=10) == "synthetic-warmed-token"
        assert fresh_transport.counts == {"oauth": 1, "models": 1, "balance": 0, "inference": 0}
        assert fresh._auth_task is None
    finally:
        await fresh.aclose()


async def test_model_catalog_once_only_before_inference():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": MODEL}]})

    transport = BoundedTransport(httpx.MockTransport(handler), secret="synthetic-model-key")
    await transport.handle_async_request(httpx.Request("GET", BASE + "/models"))
    with pytest.raises(ProviderError, match="bounded_models_limit_or_after_inference"):
        await transport.handle_async_request(httpx.Request("GET", BASE + "/models"))
    assert calls == [BASE + "/models"]
    fresh = BoundedTransport(httpx.MockTransport(handler), secret="synthetic-model-key")
    fresh.counts["inference"] = 1
    with pytest.raises(ProviderError, match="bounded_models_limit_or_after_inference"):
        await fresh.handle_async_request(httpx.Request("GET", BASE + "/models"))
    assert len(calls) == 1


@pytest.mark.parametrize("catalog", [{"data": []}, {"data": [{"id": "other-model"}]}, {"data": None}, []])
async def test_missing_reviewed_model_is_not_startup_success(catalog):
    transport = BoundedTransport(
        httpx.MockTransport(lambda r: httpx.Response(200, json=catalog)), secret="synthetic-model-key"
    )
    with pytest.raises(ProviderError, match="bounded_model_not_listed"):
        await transport.handle_async_request(httpx.Request("GET", BASE + "/models"))
    assert transport.counts["models"] == 1 and transport.counts["inference"] == 0
