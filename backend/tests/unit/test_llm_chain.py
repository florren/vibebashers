"""Failover, replay-кассеты, rate limiter, пул ключей, GigaChat через фиктивный транспорт."""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.contracts.registry import deref
from app.llm.base import LLMProfile, Message, ProviderError, Usage
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider, analyze
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.ratelimit import RateLimiter
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore, request_hash

SCHEMA = deref("agent/normalization")
PROFILE = LLMProfile(code="test_main", provider="gigachat", model="GigaChat-2-Max")
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
