"""Failover, replay-кассеты, rate limiter, пул ключей, GigaChat через фиктивный транспорт."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

from app.api.settings import public_openrouter_env_key
from app.config import Settings
from app.contracts.registry import deref
from app.llm.base import LLMProfile, Message, ProviderError, Usage
from app.llm.failover import ProviderChain, build_chain, default_profile, profile_by_code
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider, analyze
from app.llm.openai_compat import (
    DEFAULT_MODEL_IDS,
    PREFERRED_REPLACEMENT,
    OpenAICompatProvider,
    deactivation_plan,
    openrouter_deactivation_plan,
    parse_key_payload,
)
from app.llm.ratelimit import RateLimiter
from app.llm.smoke import parse_args, resolve_profile
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore, request_hash

SCHEMA = deref("agent/normalization")
PROFILE = LLMProfile(code="test_main", provider="gigachat", model="GigaChat-3-Pro")
TEXT = "Опять списали комиссию 150 ₽ за QR, верните деньги!"
MSGS: list[Message] = [{"role": "user", "content": TEXT}]
VALID = MockProvider().fill(
    SCHEMA, analyze(TEXT), random.Random(0)
)  # валидный «ответ модели» для фиктивных транспортов


class Failing:
    def __init__(self, name: str, kind: str = "network", sleep: float = 0.0) -> None:
        self.name, self.kind, self.sleep = name, kind, sleep
        self.calls = 0

    async def complete_structured(self, messages: Any, schema: Any, profile: Any, *, timeout_s: float) -> Any:
        self.calls += 1
        if self.sleep:
            await asyncio.sleep(self.sleep)
        raise ProviderError(self.kind, "boom")  # type: ignore[arg-type]

    async def stream(self, messages: Any, profile: Any, *, timeout_s: float) -> AsyncIterator[str]:
        raise ProviderError("network", "boom")
        yield ""


class Good:
    name = "gigachat"

    async def complete_structured(self, messages: Any, schema: Any, profile: Any, *, timeout_s: float) -> Any:
        obj, _, raw = await MockProvider().complete_structured(messages, schema, profile, timeout_s=timeout_s)
        return (
            obj,
            Usage(
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=40,
                provider="gigachat",
                model=profile.model,
                source="live",
            ),
            raw,
        )

    async def stream(self, messages: Any, profile: Any, *, timeout_s: float) -> AsyncIterator[str]:
        for w in ("Здравствуйте, ", "разбираемся."):
            yield w


async def test_failover_to_mock_never_stops(tmp_path) -> None:
    chain = ProviderChain(
        [Failing("gigachat", "rate_limit"), Failing("openai_compatible", "auth")], rate_limiter=RateLimiter()
    )
    res = await chain.complete_structured(MSGS, SCHEMA, PROFILE, context="fast_path")
    assert res.provider == "mock" and res.fallback_mock and res.error and "rate_limit" in res.error
    assert [a.provider for a in res.attempts] == ["gigachat", "openai_compatible", "mock"]


async def test_timeout_by_context() -> None:
    chain = ProviderChain([Failing("gigachat", sleep=1.0)], rate_limiter=RateLimiter(), timeouts={"detector": 0.05})
    assert chain.timeout_for("fast_path") == 8.0 and chain.timeout_for("default") == 30.0
    res = await chain.complete_structured(MSGS, SCHEMA, PROFILE, context="detector")
    assert res.provider == "mock" and "timeout" in (res.attempts[0].error or "")


async def test_record_then_replay(tmp_path) -> None:
    store = CassetteStore(tmp_path / "cassettes")
    rec_chain = ProviderChain([Good()], record_store=store, rate_limiter=RateLimiter())
    live = await rec_chain.complete_structured(MSGS, SCHEMA, PROFILE)
    assert live.provider == "gigachat" and live.usage.source == "live"
    assert (tmp_path / "cassettes/gigachat.jsonl").exists() and len(store) == 1
    # новый процесс: только replay + mock, промах → mock, попадание → replay
    store2 = CassetteStore(tmp_path / "cassettes")
    chain = ProviderChain([ReplayProvider(store2, speed=1000)], rate_limiter=RateLimiter())
    hit = await chain.complete_structured(MSGS, SCHEMA, PROFILE)
    assert hit.provider == "replay" and hit.obj == live.obj and hit.usage.source == "replay"
    miss = await chain.complete_structured([{"role": "user", "content": "другой текст"}], SCHEMA, PROFILE)
    assert miss.provider == "mock" and miss.attempts[0].error and "miss" in miss.attempts[0].error


def test_request_hash_normalizes_whitespace() -> None:
    a = request_hash("gigachat", "m", [{"role": "user", "content": "привет   мир "}], SCHEMA)
    b = request_hash("gigachat", "m", [{"role": "user", "content": "привет мир"}], SCHEMA)
    c = request_hash("gigachat", "m", [{"role": "user", "content": "привет мир!"}], SCHEMA)
    assert a == b != c and len(a) == 64


async def test_stream_failover() -> None:
    chain = ProviderChain([Failing("gigachat"), Good()], rate_limiter=RateLimiter())
    out = "".join([c async for c in chain.stream(MSGS, PROFILE)])
    assert out == "Здравствуйте, разбираемся."


async def test_rate_limiter_rpm_and_rpd() -> None:
    rl = RateLimiter(max_wait_s=0.0)
    for _ in range(3):
        await rl.acquire("p", rpm=3, rpd=4)
    with pytest.raises(ProviderError) as e:
        await rl.acquire("p", rpm=3, rpd=4)
    assert e.value.kind == "rate_limit"
    rl2 = RateLimiter(max_wait_s=5.0)
    for _ in range(2):
        await rl2.acquire("q", rpm=None, rpd=2)
    with pytest.raises(ProviderError):
        await rl2.acquire("q", rpm=None, rpd=2)


def test_key_pool_picks_max_remaining_and_cools_down() -> None:
    pool = KeyPool([ApiKey("a", "s1", tokens_used=40_000_000), ApiKey("b", "s2", tokens_used=10_000_000)])
    assert pool.pick().label == "b"
    pool.mark_error(pool.pick(), ProviderError("rate_limit", "429", retry_after_s=60))
    assert pool.pick().label == "a"
    pool.mark_error(pool.pick(), ProviderError("quota", "limit"))
    with pytest.raises(ProviderError) as e:
        pool.pick()
    assert e.value.kind == "quota"
    assert KeyPool.from_env(None, "x").keys[0].label == "gigachat_env_2"


def _gigachat_transport(state: dict[str, Any]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        state.setdefault("calls", []).append((req.method, req.url.path, req.headers.get("Authorization", "")[:12]))
        if req.url.path.endswith("/oauth"):
            auth = req.headers["Authorization"]
            if auth == "Basic bad":
                return httpx.Response(401, json={"message": "bad key"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{auth[-2:]}",
                    "expires_at": int((asyncio.get_event_loop().time() + 10_000) * 1000) + 1_800_000_000_000,
                },
            )
        if req.url.path.endswith("/chat/completions"):
            tok = req.headers["Authorization"]
            if tok.endswith("k1") and state.get("k1_429", True):
                return httpx.Response(429, headers={"Retry-After": "30"}, json={"message": "Too many requests"})
            body = json.loads(req.content)
            n = state.get("bad_first", 0)
            if n:
                state["bad_first"] = n - 1
                content = '{"negativity": "много"}'
            else:
                content = "```json\n" + json.dumps({**VALID, "negativity": 80}, ensure_ascii=False) + "\n```"
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
                    "model": body["model"],
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_gigachat_oauth_key_rotation_and_repair() -> None:
    state: dict[str, Any] = {"bad_first": 1}
    pool = KeyPool([ApiKey("k1", "k1", tokens_used=0), ApiKey("k2", "k2", tokens_used=1000)])
    prov = GigaChatProvider(
        pool,
        oauth_url="https://oauth.test/api/v2/oauth",
        base_url="https://gc.test/api/v1",
        transport=_gigachat_transport(state),
    )
    obj, usage, raw = await prov.complete_structured(MSGS, SCHEMA, PROFILE, timeout_s=5)
    assert obj["negativity"] == 80 and obj["sentiment"] == "negative"
    assert (
        usage.key_label == "k2" and usage.prompt_tokens == 240 and usage.source == "live"
    )  # 2 попытки: кривой JSON → исправленный
    k1, k2 = pool.keys
    assert k1.last_error and k1.last_error.startswith("rate_limit") and not k1.available()
    assert k2.tokens_used == 1000 + 360 and k2.requests_today == 2 and k2.access_token == "tok-k2"
    # повторный вызов — токен из кэша, OAuth не дёргается
    before = len([c for c in state["calls"] if c[1].endswith("/oauth")])
    await prov.complete_structured(MSGS, SCHEMA, PROFILE, timeout_s=5)
    assert len([c for c in state["calls"] if c[1].endswith("/oauth")]) == before
    await prov.aclose()


async def test_gigachat_oauth_and_chat_urls_profile_base_url() -> None:
    oauth_checks: list[str] = []
    chat_urls: list[str] = []
    default_base = "https://gigachat.devices.sberbank.ru/api/v1"
    oauth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    ultra_base = "https://api.giga.chat/v1"

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/v2/oauth":
            auth = req.headers["Authorization"]
            assert auth.startswith("Basic ") and len(auth) > 12
            assert req.headers.get("RqUID")
            assert req.headers.get("Content-Type") == "application/x-www-form-urlencoded"
            assert req.content.decode() == "scope=GIGACHAT_API_PERS"
            oauth_checks.append(auth[:12])
            return httpx.Response(
                200,
                json={
                    "access_token": "tok-test",
                    "expires_at": int((asyncio.get_event_loop().time() + 10_000) * 1000) + 1_800_000_000_000,
                },
            )
        if path.endswith("/chat/completions"):
            chat_urls.append(str(req.url))
            content = json.dumps({**VALID, "negativity": 50}, ensure_ascii=False)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        return httpx.Response(404)

    pool = KeyPool([ApiKey("k1", "c2VjcmV0")])
    prov = GigaChatProvider(
        pool,
        oauth_url=oauth_url,
        base_url=default_base,
        scope="GIGACHAT_API_PERS",
        transport=httpx.MockTransport(handler),
    )
    profile_default = LLMProfile(code="t", provider="gigachat", model="GigaChat-3-Pro")
    await prov.complete_structured(MSGS, SCHEMA, profile_default, timeout_s=5)
    assert oauth_checks and chat_urls[0] == f"{default_base}/chat/completions"

    profile_ultra = LLMProfile(code="ultra", provider="gigachat", model="GigaChat-3-Pro", base_url=ultra_base)
    await prov.complete_structured(MSGS, SCHEMA, profile_ultra, timeout_s=5)
    assert chat_urls[-1] == f"{ultra_base}/chat/completions"
    await prov.aclose()


def test_default_profile_gigachat_base_url_from_settings() -> None:
    settings = SimpleNamespace(
        llm_provider="gigachat",
        gigachat_model="GigaChat-3-Pro",
        gigachat_base_url="https://api.giga.chat/v1",
        openrouter_base_url="https://openrouter.ai/api/v1",
    )
    profile = default_profile(settings)
    assert profile.model == "GigaChat-3-Pro"
    assert profile.base_url == "https://api.giga.chat/v1"


async def test_gigachat_bad_key_is_auth_error() -> None:
    pool = KeyPool([ApiKey("bad", "bad")])
    prov = GigaChatProvider(
        pool,
        oauth_url="https://oauth.test/api/v2/oauth",
        base_url="https://gc.test/api/v1",
        transport=_gigachat_transport({}),
    )
    with pytest.raises(ProviderError) as e:
        await prov.complete_structured(MSGS, SCHEMA, PROFILE, timeout_s=5)
    assert e.value.kind == "auth" and not pool.keys[0].is_active


async def test_openai_compat_falls_back_from_json_schema_to_json_object() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body["response_format"]["type"])
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "response_format not supported"})
        content = json.dumps({**VALID, "sentiment": "neutral", "negativity": 10})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    prov = OpenAICompatProvider("key", "https://or.test/api/v1", transport=httpx.MockTransport(handler))
    p = LLMProfile(code="or", provider="openai_compatible", model="x/free", price_in_per_1m=0, price_out_per_1m=0)
    obj, usage, _ = await prov.complete_structured(MSGS, SCHEMA, p, timeout_s=5)
    assert seen == ["json_schema", "json_object"] and obj["sentiment"] == "neutral" and usage.cost_rub == 0
    await prov.aclose()


def test_schema_for_model_drops_title() -> None:
    from app.agent.prompts import load as load_prompt
    from app.llm.gigachat import schema_for_model

    raw = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:test",
        "title": "не копировать",
        "examples": [{"title": "не копировать"}],
        "type": "object",
        "required": ["overall_ru"],
        "properties": {"overall_ru": {"type": "string"}},
    }
    sent = schema_for_model(raw)
    assert "title" not in sent and "examples" not in sent and sent["required"] == ["overall_ru"]
    body = load_prompt("transcript_report").body
    for field in ("findings", "script_compliance", "overall_ru", "action_plan_ru", "confidence"):
        assert field in body
    for stale in ("summary_ru", "manager_actions_ru", "`script_steps`", "client_signal"):
        assert stale not in body


async def test_invalid_oauth_key_is_skipped_for_live_key() -> None:
    """Ключ с большим остатком выбран первым, OAuth 400 — auth; следующий живой ключ делает chat."""
    chats: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/oauth"):
            if req.headers["Authorization"] == "Basic bad":
                return httpx.Response(400, json={"code": 4, "message": "Can't decode 'Authorization' header"})
            return httpx.Response(200, json={"access_token": "tok-good", "expires_at": int(time.time() + 3600) * 1000})
        chats.append(req.headers.get("Authorization", ""))
        content = json.dumps({**VALID, "negativity": 40}, ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    pool = KeyPool([ApiKey("k1", "good", tokens_used=5_000), ApiKey("k2", "bad", tokens_used=0)])
    prov = GigaChatProvider(
        pool,
        oauth_url="https://oauth.test/api/v2/oauth",
        base_url="https://gc.test/api/v1",
        transport=httpx.MockTransport(handler),
    )
    obj, usage, _raw = await prov.complete_structured(MSGS, SCHEMA, PROFILE, timeout_s=5)
    assert obj["negativity"] == 40
    assert usage.key_label == "k1"
    assert chats == ["Bearer tok-good"]
    assert pool.keys[1].is_active is False
    assert pool.keys[0].is_active is True
    await prov.aclose()


def _chain_settings(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "llm_chain": "gigachat,openai_compat,replay,mock",
        "gigachat_auth_key_1": "gigachat-key",
        "gigachat_auth_key_2": None,
        "gigachat_oauth_url": "https://oauth.test/api/v2/oauth",
        "gigachat_base_url": "https://gc.test/api/v1",
        "gigachat_scope": "GIGACHAT_API_PERS",
        "gigachat_verify_ssl": False,
        "openrouter_api_key": "test-key",
        "openrouter_base_url": "https://openrouter.ai/api/v1",
        "local_llm_base_url": None,
        "openrouter_budget_usd": 10,
        "app_port": 8000,
        "cassettes_dir": str(tmp_path),
        "llm_record": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def _aclose_chain(chain: ProviderChain) -> None:
    for prov in chain.providers:
        close = getattr(prov, "aclose", None)
        if close is not None:
            await close()


def _chat_json(extra: dict[str, Any] | None = None) -> httpx.Response:
    content = json.dumps({**VALID, **(extra or {}), "negativity": 12}, ensure_ascii=False)
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    )


async def test_openrouter_headers_three_models_valid_json() -> None:
    paths: list[str] = []
    models: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        assert req.headers["X-Title"] == "CX Pulse Control"
        assert req.headers["HTTP-Referer"] == "http://localhost:8000"
        assert req.headers["Authorization"] == "Bearer test-key"
        body = json.loads(req.content)
        models.append(body["model"])
        parsed = json.loads(json.dumps({**VALID, "negativity": 12}))
        assert isinstance(parsed, dict)
        return _chat_json()

    prov = OpenAICompatProvider(
        "test-key",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
        budget_usd=10,
        http_referer="http://localhost:8000",
    )
    asked = (*DEFAULT_MODEL_IDS, "nvidia/nemotron-3-super-120b-a12b:free")
    for model in asked:
        profile = LLMProfile(code="or", provider="openai_compatible", model=model)
        obj, _usage, raw = await prov.complete_structured(MSGS, SCHEMA, profile, timeout_s=5)
        assert obj["negativity"] == 12
        json.loads(raw)
    assert models == list(asked)
    assert paths and all(path.endswith("/chat/completions") for path in paths)
    await prov.aclose()


async def test_openai_provider_skips_gigachat_profile_before_http() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(500)

    prov = OpenAICompatProvider(
        "test-key",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
        http_referer="http://localhost:8000",
    )
    profile = LLMProfile(code="gigachat_ultra", provider="gigachat", model="GigaChat-3-Pro")
    with pytest.raises(ProviderError) as err:
        await prov.complete_structured(MSGS, SCHEMA, profile, timeout_s=5)
    assert err.value.kind == "miss"
    with pytest.raises(ProviderError) as stream_err:
        async for _chunk in prov.stream(MSGS, profile, timeout_s=5):
            pass
    assert stream_err.value.kind == "miss"
    assert calls == []
    await prov.aclose()


async def test_paid_model_over_budget_is_quota_without_chat() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("/key"):
            return httpx.Response(
                200,
                json={"data": {"limit": 50, "usage": 11, "limit_remaining": 39, "is_free_tier": False}},
            )
        return _chat_json()

    prov = OpenAICompatProvider(
        "test-key",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
        budget_usd=10,
        http_referer="http://localhost:8000",
    )
    profile = LLMProfile(code="paid", provider="openai_compatible", model="openai/gpt-4o")
    with pytest.raises(ProviderError) as err:
        await prov.complete_structured(MSGS, SCHEMA, profile, timeout_s=5)
    assert err.value.kind == "quota"
    assert paths == ["/api/v1/key"]
    await prov.aclose()


async def test_paid_model_key_error_is_quota_without_chat() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(503, json={"error": "down"})

    prov = OpenAICompatProvider(
        "test-key", "https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler), budget_usd=10
    )
    profile = LLMProfile(code="paid", provider="openai_compatible", model="openai/gpt-4o")
    with pytest.raises(ProviderError) as err:
        await prov.complete_structured(MSGS, SCHEMA, profile, timeout_s=5)
    assert err.value.kind == "quota"
    assert paths == ["/api/v1/key"]
    await prov.aclose()


async def test_gigachat_provider_misses_openrouter_profile_without_oauth() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(500)

    pool = KeyPool([ApiKey("k1", "secret")])
    prov = GigaChatProvider(
        pool,
        oauth_url="https://oauth.test/api/v2/oauth",
        base_url="https://gc.test/api/v1",
        transport=httpx.MockTransport(handler),
    )
    profile = LLMProfile(code="or_gpt_oss_120b", provider="openai_compatible", model="openai/gpt-oss-120b:free")
    with pytest.raises(ProviderError) as err:
        await prov.complete_structured(MSGS, SCHEMA, profile, timeout_s=5)
    assert err.value.kind == "miss"
    with pytest.raises(ProviderError) as stream_err:
        async for _chunk in prov.stream(MSGS, profile, timeout_s=5):
            pass
    assert stream_err.value.kind == "miss"
    assert calls == []
    assert pool.keys[0].access_token is None
    await prov.aclose()


def test_settings_default_chain_puts_openai_between_gigachat_and_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LLM_CHAIN", "OPENROUTER_BUDGET_USD", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    parts = [part.strip() for part in settings.llm_chain.split(",") if part.strip()]
    gigachat_at = parts.index("gigachat")
    assert parts[gigachat_at + 1] == "openai_compat"
    assert parts[gigachat_at + 2] == "replay"
    assert settings.openrouter_budget_usd == 10
    assert settings.llm_provider == "mock"


async def test_build_chain_names_with_openrouter_and_gigachat_keys(tmp_path: Path) -> None:
    chain = build_chain(_chain_settings(tmp_path), transport=httpx.MockTransport(lambda req: httpx.Response(404)))
    try:
        assert chain.names == ["gigachat", "openai_compatible", "replay", "mock"]
        compat = next(p for p in chain.providers if isinstance(p, OpenAICompatProvider))
        assert compat.http_referer == "http://localhost:8000"
        assert compat.budget_usd == 10
    finally:
        await _aclose_chain(chain)


async def test_replay_mock_chain_skips_openai_even_with_key(tmp_path: Path) -> None:
    chain = build_chain(
        _chain_settings(tmp_path, llm_chain="replay,mock", openrouter_api_key="test-key"),
        transport=httpx.MockTransport(lambda req: httpx.Response(404)),
    )
    try:
        assert chain.names == ["replay", "mock"]
        assert "openai_compatible" not in chain.names
    finally:
        await _aclose_chain(chain)


async def test_local_openai_without_key_uses_local_url_and_no_authorization(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("Authorization"))
        assert req.url.path.endswith("/chat/completions")
        assert "openrouter.ai" not in str(req.url)
        return _chat_json()

    settings = _chain_settings(
        tmp_path,
        llm_chain="openai_compat",
        openrouter_api_key=None,
        local_llm_base_url="http://127.0.0.1:11434/v1",
    )
    profile = profile_by_code(settings, "local_openai")
    assert profile.model == "local"
    assert profile.base_url == "http://127.0.0.1:11434/v1"
    assert profile.extra.get("local") is True
    chain = build_chain(settings, transport=httpx.MockTransport(handler))
    try:
        assert chain.names[0] == "openai_compatible"
        prov = chain.providers[0]
        assert isinstance(prov, OpenAICompatProvider)
        assert prov.api_key is None
        obj, _usage, _raw = await prov.complete_structured(MSGS, SCHEMA, profile, timeout_s=5)
        assert obj["negativity"] == 12
        assert seen == [None]
    finally:
        await _aclose_chain(chain)


def test_smoke_profile_flag_resolves_model_without_network() -> None:
    args = parse_args(["--profile", "or_gpt_oss_120b"])
    settings = SimpleNamespace(
        llm_provider="mock",
        openrouter_base_url="https://openrouter.ai/api/v1",
        local_llm_base_url=None,
    )
    profile = resolve_profile(settings, args.profile)
    assert profile.model == "openai/gpt-oss-120b:free"
    assert parse_args([]).profile is None
    assert resolve_profile(settings, None).provider == "mock"


def test_deactivation_plan_suggests_super_or_first_free() -> None:
    available = ["other/paid", PREFERRED_REPLACEMENT, "openai/gpt-oss-120b:free"]
    plan = deactivation_plan(available)
    missing = {item["model"] for item in plan}
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in missing
    assert "openrouter/owl-alpha" in missing
    assert "openai/gpt-oss-120b:free" not in missing
    assert all(item["is_active"] is False and item["suggested_model"] == PREFERRED_REPLACEMENT for item in plan)
    fallback = deactivation_plan(["meta/llama-3:free", "vendor/paid"])
    assert fallback and all(item["suggested_model"] == "meta/llama-3:free" for item in fallback)
    assert deactivation_plan([]) == []
    assert deactivation_plan(list(DEFAULT_MODEL_IDS)) == []


async def test_models_catalog_builds_plan_on_mock_transport() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/models")
        assert req.headers["HTTP-Referer"] == "http://localhost:8000"
        return httpx.Response(
            200,
            json={"data": [{"id": PREFERRED_REPLACEMENT}, {"id": "openai/gpt-oss-120b:free"}]},
        )

    prov = OpenAICompatProvider(
        "test-key",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
        http_referer="http://localhost:8000",
    )
    plan = await openrouter_deactivation_plan(prov)
    assert any(
        item["model"] == "openrouter/owl-alpha" and item["suggested_model"] == PREFERRED_REPLACEMENT for item in plan
    )
    await prov.aclose()

    empty = OpenAICompatProvider(
        "test-key",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": []})),
    )
    assert await openrouter_deactivation_plan(empty) == []
    await empty.aclose()

    failed = OpenAICompatProvider(
        "test-key", "https://openrouter.ai/api/v1", transport=httpx.MockTransport(lambda req: httpx.Response(503))
    )
    assert await openrouter_deactivation_plan(failed) == []
    await failed.aclose()


async def test_deactivation_plan_empty_when_base_url_is_not_openrouter() -> None:
    """Локальный каталог без трёх id OpenRouter план деактивации не строит."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "local-llm"}]})

    prov = OpenAICompatProvider(
        "test-key",
        "http://127.0.0.1:11434/v1",
        transport=httpx.MockTransport(handler),
    )
    assert await openrouter_deactivation_plan(prov) == []
    await prov.aclose()


def test_llm_profiles_yaml_keeps_three_models_and_local_openai() -> None:
    root = Path(__file__).resolve().parents[3]
    data = yaml.safe_load((root / "data/llm_profiles.yaml").read_text(encoding="utf-8"))
    by_code = {row["code"]: row for row in data["llm_profiles"]}
    assert by_code["or_nemotron_ultra"]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert by_code["or_owl_alpha"]["model"] == "openrouter/owl-alpha"
    assert by_code["or_gpt_oss_120b"]["model"] == "openai/gpt-oss-120b:free"
    local = by_code["local_openai"]
    assert local["provider"] == "openai_compatible"
    assert local["model"] == "local"
    assert local["base_url"] == ""
    assert local["role"] == "bench_only"
    assert local["is_active"] is True
    assert local["extra"]["local"] is True


def test_parse_key_payload_balance_and_rpd() -> None:
    paid = parse_key_payload({"data": {"limit": 20, "usage": 3, "limit_remaining": 17, "is_free_tier": False}})
    free = parse_key_payload({"data": {"limit": 0, "usage": 0, "limit_remaining": 0, "is_free_tier": True}})
    assert paid["balance_usd"] == 17 and paid["rpd_limit"] == 1000
    assert paid["limit"] == 20 and paid["usage"] == 3 and paid["limit_remaining"] == 17
    assert free["balance_usd"] == 0 and free["rpd_limit"] == 50 and free["is_free_tier"] is True


def test_public_openrouter_env_key_balance_and_duplicate_hint() -> None:
    paid = parse_key_payload({"data": {"limit": 20, "usage": 3, "limit_remaining": 17, "is_free_tier": False}})
    free = parse_key_payload({"data": {"limit": 0, "usage": 0, "limit_remaining": 0, "is_free_tier": True}})
    saved = [{"id": 1, "provider": "gigachat", "key_hint": "…hint", "key_enc": "enc1:stored"}]
    allowed = {
        "id",
        "provider",
        "label",
        "tokens_used",
        "tokens_limit",
        "requests_today",
        "rpd_limit",
        "balance_usd",
        "is_active",
        "last_error",
    }

    paid_rows = public_openrouter_env_key(saved, paid, key_hint="…hint", last_error=None)
    assert len(paid_rows) == 2 and len(saved) == 1 and saved[0]["key_enc"] == "enc1:stored"
    added = paid_rows[-1]
    assert added["provider"] == "openai_compatible"
    assert added["balance_usd"] == 17 and added["rpd_limit"] == 1000
    assert added["id"] not in {item["id"] for item in saved}
    assert set(added) <= allowed
    assert "key_enc" not in added and "key" not in added
    assert "enc1:" not in json.dumps(added)

    free_rows = public_openrouter_env_key([], free, key_hint="…free", last_error=None)
    assert free_rows[-1]["balance_usd"] == 0 and free_rows[-1]["rpd_limit"] == 50
    assert "key_enc" not in free_rows[-1] and set(free_rows[-1]) <= allowed

    same_hint = [{"id": 4, "provider": "openai_compatible", "key_hint": "…hint", "key_enc": "enc1:stored"}]
    duplicate = public_openrouter_env_key(same_hint, paid, key_hint="…hint", last_error=None)
    assert len(duplicate) == 1 and duplicate[0]["id"] == 4

    failed = public_openrouter_env_key([], None, key_hint="…err", last_error="key 401")
    assert failed[0]["last_error"] == "key 401"
    assert failed[0]["balance_usd"] is None and failed[0]["rpd_limit"] is None
    assert "key_enc" not in failed[0]


async def test_fetch_key_reads_balance_over_mock_transport() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/key")
        assert req.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200, json={"data": {"limit": 20, "usage": 3, "limit_remaining": 17, "is_free_tier": False}}
        )

    prov = OpenAICompatProvider(
        "test-key",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
        http_referer="http://localhost:8000",
    )
    info = await prov.fetch_key()
    assert info["balance_usd"] == 17 and info["rpd_limit"] == 1000
    await prov.aclose()


def test_cassettes_have_no_secrets() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    bad = re.compile(
        r"(Bearer\s+[A-Za-z0-9\-_\.]{20,}|Basic\s+[A-Za-z0-9+/=]{20,}|sk-or-[A-Za-z0-9]{10,}|\+7\s?\d{3}\s?\d{3}\s?\d{2}\s?\d{2}|\b\d{16}\b)"
    )
    for f in (root / "data/cassettes").glob("*.jsonl"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            assert not bad.search(line), f"{f.name}:{i}: похоже на секрет или ПДн"
