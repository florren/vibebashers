"""Actual graph + native PG ledger + fake HTTP; outputs explicitly FAKE, never release assets."""

import datetime as dt
import json
import uuid
from dataclasses import replace

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
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.replay11_bank import configure_profile, seed_bank
from tests.integration.conftest import rebuild_schema

pytestmark = pytest.mark.integration


@pytest.fixture
async def bank_dsn(migrated_db):
    params = conninfo_to_dict(migrated_db.replace("postgresql+psycopg://", "postgresql://", 1))
    name = "cx_replay11_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(make_conninfo(**params), autocommit=True) as admin:
        await admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    bank_url = make_conninfo(**{**params, "dbname": name})
    # Alembic expects a URL; preserve original escaped credential fields via SQLAlchemy.
    from sqlalchemy.engine import make_url

    url = make_url(migrated_db).set(database=name).render_as_string(hide_password=False)
    rebuild_schema(url)
    try:
        yield bank_url, url
    finally:
        async with await psycopg.AsyncConnection.connect(make_conninfo(**params), autocommit=True) as admin:
            await admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))


@pytest.mark.parametrize("mode", ["valid", "native_rpd", "unknown_usage"])
async def test_fake_live_v2_to_strict_replay_and_changed_context(migrated_db, bank_dsn, monkeypatch, tmp_path, mode):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    get_settings.cache_clear()
    rebuild_schema(migrated_db)
    accounting_dsn = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    dsn, bank_url = bank_dsn
    secret = "synthetic-replay11-only-fake-credential-" + uuid.uuid4().hex
    profile = LLMProfile(
        code="replay11-fake-proof",
        provider="gigachat",
        model=MODEL,
        base_url=BASE,
        role="main",
        temperature=0,
        rpd_limit=2 if mode == "native_rpd" else 6,
    )
    async with await psycopg.AsyncConnection.connect(accounting_dsn) as accounting_conn:
        row = await (
            await accounting_conn.execute(
                "insert into llm_profiles(code,provider,model,role,rpd_limit) values(%s,'gigachat',%s,'main',%s) returning id",
                (profile.code, MODEL, profile.rpd_limit),
            )
        ).fetchone()
        assert row
        profile = replace(profile, id=row[0])
    schema_calls = []

    async def handler(request):
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
    try:
        async with await psycopg.AsyncConnection.connect(dsn) as bank:
            await seed_bank(bank, dsn)
            profile = await configure_profile(bank, recording_profile(profile))
            await PostgresAccounting().connect_gigachat(
                profile, KeyFacts("gigachat", secret, BASE, 100000), {"GigaChat-Pro": 100000}, confirmed=True
            )
            if mode != "valid":
                with pytest.raises(ValueError, match="strict_replay11_llm_steps_failed"):
                    await record(bank, provider, transport, profile, tmp_path / "fake-staging", fake_transport=True)
                async with await psycopg.AsyncConnection.connect(accounting_dsn) as ledger:
                    rows = await (
                        await ledger.execute(
                            "select state,count(*) from llm_runtime.wire_attempts where profile_scope=(select 'quota:'||quota_uid from llm_profiles where id=%s) group by state",
                            (profile.id,),
                        )
                    ).fetchall()
                    assert dict(rows) == ({"known": 2} if mode == "native_rpd" else {"unknown": 1})
                assert transport.counts["inference"] == (2 if mode == "native_rpd" else 1)
                assert (await (await bank.execute("select count(*) from llm_runtime.wire_attempts")).fetchone())[0] == 0
                return
            report = await record(bank, provider, transport, profile, tmp_path / "fake-staging", fake_transport=True)
        assert report["fake_transport"] is True
        assert report["http_counts"] == {"oauth": 1, "balance": 3, "inference": 3}
        assert len(report["requests"]) == 3
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
