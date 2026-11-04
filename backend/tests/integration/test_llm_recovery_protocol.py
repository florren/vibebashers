"""Recovery composition: real PostgreSQL accounting and providers, synthetic HTTP only."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import get_settings
from app.llm.accounting import KeyFacts, PostgresAccounting
from app.llm.base import ProviderError
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.roles import select

pytestmark = pytest.mark.integration
BASE = "https://recovery.invalid/v1"
SECRET = "synthetic-recovery-credential"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture(params=["gigachat", "openai_compatible"])
async def recovery(request, migrated_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    dsn = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    kind = request.param
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        row = await (
            await conn.execute(
                "insert into llm_profiles(code,provider,model,role,temperature,rpd_limit,is_active) "
                "values(%s,%s,%s,'main',0.15,3,true) returning *",
                ("recovery-" + uuid.uuid4().hex, kind, "synthetic-model"),
            )
        ).fetchone()
    settings = get_settings().model_copy(update={"llm_provider": "gigachat" if kind == "gigachat" else "openai_compat"})
    # Use the production loader: SQL numeric values must not enter JSON as Decimal.
    profile = select(settings, [row], {"main_profile_id": row["id"]})["main"]
    assert isinstance(profile.temperature, float)
    service = PostgresAccounting()
    facts = KeyFacts(kind, SECRET + row["code"], BASE, 100 if kind == "gigachat" else None)
    calls: list[str] = []

    async def http(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "recovery.invalid"
        calls.append(request.url.path)
        if request.url.path == "/oauth":
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access",
                    "expires_at": int(dt.datetime.now(dt.UTC).timestamp() * 1000) + 60000,
                },
            )
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["temperature"] == 0.15
        # Reservation must be visible from an independent connection before HTTP.
        async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
            attempt = await (
                await conn.execute(
                    "select state from llm_runtime.wire_attempts where profile_id=%s order by admitted_at desc limit 1",
                    (profile.id,),
                )
            ).fetchone()
        assert attempt == {"state": "reserved"}
        usage = (
            None
            if getattr(requests, "missing_usage", False)
            else {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        )
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": profile.model,
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok":true}'}}
                ],
                "usage": usage,
            },
        )

    class Requests:
        missing_usage = False

    requests = Requests()

    def provider():
        transport = httpx.MockTransport(http)
        if kind == "gigachat":
            return GigaChatProvider(
                KeyPool([ApiKey("synthetic", facts.secret, tokens_limit=100)]),
                oauth_url="https://recovery.invalid/oauth",
                base_url=BASE,
                transport=transport,
            )
        return OpenAICompatProvider(facts.secret, BASE, transport=transport)

    async def reconcile():
        async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
            as_of = (await (await conn.execute("select clock_timestamp() as value")).fetchone())["value"]
        await service.reconcile(
            profile,
            facts,
            reconciliation_id=uuid.uuid4(),
            as_of=as_of,
            tokens_used=7,
            requests_today=1,
            profile_requests={f"id:{profile.id}": 1},
            confirmed=True,
            acknowledge_unknown_origin=True,
        )

    return profile, service, facts, calls, requests, provider, reconcile


async def test_reconciliation_restores_provider_and_restart_preserves_daily_cap(recovery):
    profile, service, facts, calls, _requests, make_provider, reconcile = recovery
    provider = make_provider()
    try:
        assert provider.accounting.durable
        with pytest.raises(ProviderError, match="reconciliation"):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
        assert calls == []
        await reconcile()
        obj, usage, _raw = await provider.complete_structured(
            [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
        )
        assert obj == {"ok": True} and usage.total_tokens == 5
    finally:
        await provider.aclose()
    provider = make_provider()
    try:
        await provider.complete_structured(
            [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
        )
        before = list(calls)
        with pytest.raises(ProviderError, match="суточный"):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
        assert calls == before
    finally:
        await provider.aclose()
    snapshot = await service.snapshot(profile, facts, timeout_s=5)
    assert snapshot.tokens_used == 17 and snapshot.usage_known
    assert snapshot.requests_today == snapshot.profile_requests_today == 3
    assert snapshot.profile_requests_remaining == 0


async def test_missing_usage_does_not_become_zero_or_allow_another_provider_call(recovery):
    profile, service, facts, calls, requests, make_provider, reconcile = recovery
    await reconcile()
    requests.missing_usage = True
    provider = make_provider()
    try:
        with pytest.raises(ProviderError, match="расход"):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
        before = list(calls)
        with pytest.raises(ProviderError, match="reconciliation"):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
        assert calls == before
    finally:
        await provider.aclose()
    snapshot = await service.snapshot(profile, facts, timeout_s=5)
    assert snapshot.tokens_used == 7 and not snapshot.usage_known
    assert snapshot.requests_today == snapshot.profile_requests_today == 2
