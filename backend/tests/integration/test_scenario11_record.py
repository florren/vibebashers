"""Actual graph + native PG ledger + fake HTTP; outputs explicitly FAKE, never release assets."""

import datetime as dt
import json
import uuid
from dataclasses import replace
from decimal import Decimal

import httpx
import psycopg
import pytest
from app.config import get_settings
from app.contracts.registry import deref
from app.llm.accounting import KeyFacts, PostgresAccounting
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider
from app.replay.provider import ReplayProvider
from app.replay.scenario11_record import (
    BASE,
    MODEL,
    OAUTH,
    BoundedTransport,
    fixture,
    record,
    recording_profile,
    run_graph,
)
from app.replay.store import CassetteStore

from scripts.replay11_bank import configure_profile, seed_bank
from tests.integration.conftest import rebuild_schema

pytestmark = pytest.mark.integration


@pytest.fixture
async def bank_dsn(migrated_db):
    from tests.helpers import fresh_replay11_database

    async with fresh_replay11_database(migrated_db) as value:
        yield value


@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "native_rpd",
        "unknown_usage",
        "oauth_connect_timeout",
        "delayed_oauth",
        "decimal_zero",
        "decimal_nonzero",
    ],
)
async def test_fake_live_v2_to_strict_replay_and_changed_context(migrated_db, bank_dsn, monkeypatch, tmp_path, mode):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    get_settings.cache_clear()
    rebuild_schema(migrated_db)
    accounting_dsn = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    dsn, bank_url = bank_dsn
    secret = "synthetic-replay11-only-fake-credential-" + uuid.uuid4().hex
    profile = LLMProfile(
        code="gigachat_pro"
        if mode in ("oauth_connect_timeout", "delayed_oauth", "decimal_zero", "decimal_nonzero")
        else "replay11-fake-proof",
        provider="gigachat",
        model=MODEL,
        base_url=BASE,
        role="main",
        temperature=0.7 if mode in ("oauth_connect_timeout", "delayed_oauth", "decimal_zero", "decimal_nonzero") else 0,
        rpd_limit=2 if mode == "native_rpd" else 6,
    )
    if mode in ("decimal_zero", "decimal_nonzero"):
        profile = replace(
            profile,
            price_in_per_1m=Decimal("4.50") if mode == "decimal_nonzero" else Decimal("0"),
            price_out_per_1m=Decimal("6.25") if mode == "decimal_nonzero" else Decimal("0"),
        )
    async with await psycopg.AsyncConnection.connect(accounting_dsn) as accounting_conn:
        row = await (
            await accounting_conn.execute(
                "insert into llm_profiles(id,code,provider,model,role,rpd_limit,temperature,price_in_per_1m,price_out_per_1m) overriding system value values(%s,%s,'gigachat',%s,'main',%s,%s,%s,%s) returning id,temperature,price_in_per_1m,price_out_per_1m",
                (
                    2 if mode in ("oauth_connect_timeout", "delayed_oauth", "decimal_zero", "decimal_nonzero") else 1,
                    profile.code,
                    MODEL,
                    profile.rpd_limit,
                    profile.temperature,
                    profile.price_in_per_1m,
                    profile.price_out_per_1m,
                ),
            )
        ).fetchone()
        assert row
        profile = replace(profile, id=row[0])
        if mode in ("decimal_zero", "decimal_nonzero"):
            assert isinstance(row[1], Decimal) and isinstance(row[2], Decimal) and isinstance(row[3], Decimal)
            profile = replace(profile, temperature=row[1], price_in_per_1m=row[2], price_out_per_1m=row[3])

    schema_calls = []
    warm_hosts = set()

    async def handler(request):
        if (
            mode in ("oauth_connect_timeout", "delayed_oauth", "decimal_zero", "decimal_nonzero")
            and request.url.host not in warm_hosts
        ):
            if request.extensions["timeout"]["connect"] <= 2:
                raise httpx.ConnectTimeout("controlled cold TLS requires startup", request=request)
            warm_hosts.add(request.url.host)
        if str(request.url) == BASE + "/models":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        if str(request.url) == OAUTH:
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access-replay11",
                    "expires_at": int((dt.datetime.now(dt.UTC).timestamp() + 3600) * 1000),
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json={"balance": [{"usage": "GigaChat-Pro", "value": 100000}]})
        body = json.loads(request.content)
        # Same existing schema + mock decision generator; this is explicitly fake HTTP proof.
        index = len(schema_calls)
        schema = deref(["agent/normalization", "agent/classification", "agent/decision"][index])
        schema_calls.append(schema)
        obj, _, _ = await MockProvider().complete_structured(body["messages"], schema, profile, timeout_s=5)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)}}],
                "usage": None
                if mode == "unknown_usage"
                else {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    transport = BoundedTransport(httpx.MockTransport(handler), secret=secret)
    provider = GigaChatProvider(
        KeyPool([ApiKey("fake", secret, tokens_limit=100000)]), oauth_url=OAUTH, base_url=BASE, transport=transport
    )
    observed_prices = []
    original_complete = provider.complete_structured

    async def observed_complete(messages, schema, actual_profile, *, timeout_s):
        if mode in ("decimal_zero", "decimal_nonzero"):
            assert type(actual_profile.price_in_per_1m) is float and type(actual_profile.price_out_per_1m) is float
            assert Decimal(str(actual_profile.price_in_per_1m)) == profile.price_in_per_1m
            assert Decimal(str(actual_profile.price_out_per_1m)) == profile.price_out_per_1m
            assert actual_profile.id == 2 and actual_profile.rpd_limit == profile.rpd_limit
            assert actual_profile.cost(10, 20) == pytest.approx(0.00017 if mode == "decimal_nonzero" else 0)
            observed_prices.append(True)
        return await original_complete(messages, schema, actual_profile, timeout_s=timeout_s)

    monkeypatch.setattr(provider, "complete_structured", observed_complete)
    try:
        async with await psycopg.AsyncConnection.connect(dsn) as bank:
            await seed_bank(bank, dsn)
            profile = await configure_profile(bank, recording_profile(profile))
            await PostgresAccounting().connect_gigachat(
                profile, KeyFacts("gigachat", secret, BASE, 100000), {"GigaChat-Pro": 100000}, confirmed=True
            )
            if mode != "oauth_connect_timeout":
                from scripts.replay11_record import warm_recording_provider

                await warm_recording_provider(provider, profile)
            if mode in ("native_rpd", "unknown_usage", "oauth_connect_timeout"):
                with pytest.raises(ValueError, match="strict_replay11_llm_steps_failed"):
                    await record(bank, provider, transport, profile, tmp_path / "fake-staging", fake_transport=True)
                async with await psycopg.AsyncConnection.connect(accounting_dsn) as ledger:
                    rows = await (
                        await ledger.execute(
                            "select state,count(*) from llm_runtime.wire_attempts where profile_scope=(select 'quota:'||quota_uid from llm_profiles where id=%s) group by state",
                            (profile.id,),
                        )
                    ).fetchall()
                    assert dict(rows) == (
                        {"known": 2}
                        if mode == "native_rpd"
                        else {}
                        if mode == "oauth_connect_timeout"
                        else {"unknown": 1}
                    )
                assert transport.counts["inference"] == (
                    2 if mode == "native_rpd" else 0 if mode == "oauth_connect_timeout" else 1
                )
                assert (await (await bank.execute("select count(*) from llm_runtime.wire_attempts")).fetchone())[0] == 0
                return
            report = await record(bank, provider, transport, profile, tmp_path / "fake-staging", fake_transport=True)
        assert report["fake_transport"] is True
        assert report["http_counts"] == {"oauth": 1, "models": 1, "balance": 3, "inference": 3}
        assert len(report["requests"]) == 3
        if mode in ("decimal_zero", "decimal_nonzero"):
            assert observed_prices == [True, True, True]

        if mode == "delayed_oauth":
            assert warm_hosts == {"ngw.devices.sberbank.ru", "api.giga.chat"}
            assert provider._auth_task is None
            async with await psycopg.AsyncConnection.connect(accounting_dsn) as ledger:
                unchanged_temperature = (
                    await (
                        await ledger.execute("select temperature from llm_profiles where id=%s", (profile.id,))
                    ).fetchone()
                )[0]
                assert float(unchanged_temperature) == 0.7 and profile.temperature == 0

    finally:
        await provider.aclose()
    async with await psycopg.AsyncConnection.connect(accounting_dsn) as bank:
        attempts = await (
            await bank.execute(
                "select state,count(*) from llm_runtime.wire_attempts where profile_scope=(select 'quota:'||quota_uid from llm_profiles where id=(select max(id) from llm_profiles)) group by state"
            )
        ).fetchall()
        assert dict(attempts) == {"known": 3}
    async with await psycopg.AsyncConnection.connect(dsn) as bank:
        assert (await (await bank.execute("select count(*) from llm_runtime.wire_attempts")).fetchone())[0] == 0
    rebuild_schema(bank_url)
    store = CassetteStore(tmp_path / "fake-staging/FAKE-DO-NOT-PUBLISH")
    chain = ProviderChain([ReplayProvider(store, speed=10000)], append_mock=False)
    assert chain.names == ["replay"] and chain.strict
    async with await psycopg.AsyncConnection.connect(dsn) as bank:
        await seed_bank(bank, dsn)
        profile = await configure_profile(bank, recording_profile(profile))
        result = await run_graph(bank, chain, recording_profile(profile), source="replay")
        assert result["evaluation"]["counts"]["errors"] == 0
    async with await psycopg.AsyncConnection.connect(accounting_dsn) as ledger:
        unchanged = await (
            await ledger.execute(
                "select state,count(*) from llm_runtime.wire_attempts where profile_scope=(select 'quota:'||quota_uid from llm_profiles where id=%s) group by state",
                (profile.id,),
            )
        ).fetchall()
        assert dict(unchanged) == {"known": 3}
    first = report["requests"][0]
    changed = [*first["messages"][:-1], {"role": "user", "content": fixture()["text"] + " Другой контекст."}]
    with pytest.raises(ProviderError, match="нет кассеты"):
        await chain.complete_structured(changed, first["schema"], recording_profile(profile))
    # Global default keeps historic v1 behavior; explicit v2 is opt-in only.
    assert profile.extra["agent_prompt_templates"] == "v2"
    # A wrong template can't accidentally hit the v2 cassette.
    legacy = replace(profile, extra={"agent_prompt_templates": "v1"})
    from types import SimpleNamespace

    from app.agent import nodes

    with pytest.raises(ProviderError, match="нет кассеты"):
        await nodes._llm(
            SimpleNamespace(profile=legacy, chain=chain),
            "normalize",
            "agent/normalization",
            {"hints": {}, "channel": "social", "text": fixture()["text"]},
            fixture()["text"],
        )
