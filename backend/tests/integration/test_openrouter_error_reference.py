"""OpenRouter metadata переживает ошибку графа, но не снимает unknown usage."""

from __future__ import annotations

import dataclasses
import json
import uuid

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent.checkpoints import TransactionalSaver
from app.agent.graph import process_signal
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.accounting import KeyFacts, PostgresAccounting
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.llm.openai_compat import OpenAICompatProvider
from tests.helpers import dsn, new_run, sim_now

BASE = "https://openrouter.ai/api/v1"
GENERATION = "gen-1234567890-SyntheticRecovery"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture
async def openrouter_case(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_CHAIN", "openai_compat")
    get_settings.cache_clear()
    code = "or-recovery-" + uuid.uuid4().hex
    secret = "synthetic-secret-" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        pid = (
            await (
                await conn.execute(
                    "insert into llm_profiles(code,provider,model,role,rpd_limit) "
                    "values(%s,'openai_compatible','synthetic:free','main',1000) returning id",
                    (code,),
                )
            ).fetchone()
        )[0]
        await conn.execute(
            "insert into settings(key,value) values('setup_payload',%s) "
            "on conflict(key) do update set value=excluded.value",
            (Jsonb({"llm": {f"{role}_profile_id": pid for role in ("main", "fast", "twin")}}),),
        )
        observed_at = (await (await conn.execute("select clock_timestamp()")).fetchone())[0]
    profile = LLMProfile(code=code, id=pid, provider="openai_compatible", model="synthetic:free", rpd_limit=1000)
    service = PostgresAccounting()
    facts = KeyFacts("openai_compatible", secret, BASE)
    # Только собственный новый synthetic credential; не reconciliation рабочего ключа.
    await service.reconcile(
        profile,
        facts,
        reconciliation_id=uuid.uuid4(),
        as_of=observed_at,
        tokens_used=0,
        requests_today=0,
        profile_requests={f"id:{pid}": 0},
        confirmed=True,
        acknowledge_unknown_origin=True,
    )
    yield seeded, profile, facts, service
    get_settings.cache_clear()


def error_response(secret, where):
    body = {"error": {"code": 502, "message": "Untrusted provider echo " + secret}}
    if where != "header":
        body["id"] = GENERATION
    return httpx.Response(200, json=body, headers={"X-Generation-Id": GENERATION} if where != "body" else {})


@pytest.mark.parametrize("where", ["body", "header", "both"])
async def test_reference_does_not_clear_unknown_or_allow_recreated_provider(openrouter_case, where):
    url, profile, facts, service = openrouter_case
    requests = []

    def http(request):
        requests.append(request.url.path)
        return error_response(facts.secret, where)

    provider = OpenAICompatProvider(facts.secret, BASE, transport=httpx.MockTransport(http))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured([], SCHEMA, profile, timeout_s=5)
        assert error.value.kind == "bad_output" and error.value.usage is None
        assert f"generation_id={GENERATION}" in error.value.detail
        assert "provider_error_code=502" in error.value.detail
        assert facts.secret not in str(error.value)
    finally:
        await provider.aclose()
    snapshot = await service.snapshot(profile, facts, timeout_s=3)
    assert snapshot.usage_known is False and snapshot.tokens_used == 0 and snapshot.requests_today == 1
    assert snapshot.refusal is not None and snapshot.refusal.kind == "quota"
    async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
        wire = await (
            await conn.execute(
                "select state,error_kind,prompt_tokens,completion_tokens,observed_tokens "
                "from llm_runtime.wire_attempts where profile_id=%s",
                (profile.id,),
            )
        ).fetchone()
        assert wire == ("unknown", "bad_output", None, None, 0)
    restarted = OpenAICompatProvider(facts.secret, BASE, transport=httpx.MockTransport(http))
    try:
        with pytest.raises(ProviderError, match="reconciliation"):
            await restarted.complete_structured([], SCHEMA, dataclasses.replace(profile), timeout_s=5)
    finally:
        await restarted.aclose()
    assert requests == ["/api/v1/chat/completions"]
    assert (await service.snapshot(profile, facts, timeout_s=3)).requests_today == 1


async def test_reference_survives_actual_graph_step_and_reopened_checkpoint(openrouter_case):
    url, profile, facts, _ = openrouter_case
    calls = []

    def http(request):
        calls.append(request.url.path)
        return error_response(facts.secret, "header")

    provider = OpenAICompatProvider(facts.secret, BASE, transport=httpx.MockTransport(http))
    chain = ProviderChain([provider], append_mock=False)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
            rid = await new_run(conn, "Synthetic OpenRouter error reference")
            at = await sim_now(conn)
            signal = await create_signal(
                conn,
                from_api_signal(
                    {"channel_code": "chat", "text": "В приложении Банка не открывается вклад. Пожалуйста, помогите."}
                ),
                source_code="api",
                run_id=rid,
                sim_time=at,
                emit_event=False,
            )
            await conn.commit()
            assert signal["status"] == "accepted"
            state = await process_signal(conn, signal_id=signal["signal_id"], chain=chain, profile=profile)
            await conn.commit()
            assert state is not None and state["outcome"] == "awaiting_human"
            assert any(f"generation_id={GENERATION}" in error for error in state["errors"])
            assert facts.secret not in json.dumps(state["errors"])
            agent = await (
                await conn.execute(
                    "select id,thread_id from agent_runs where signal_id=%s order by id desc limit 1",
                    (signal["signal_id"],),
                )
            ).fetchone()
        # Новое соединение читает durable proof; повторных graph/LLM вызовов нет.
        async with await psycopg.AsyncConnection.connect(dsn(url)) as reopened:
            step = (
                await (
                    await reopened.execute(
                        "select input from agent_steps where run_id=%s and node='wait_human'", (agent[0],)
                    )
                ).fetchone()
            )[0]
            assert any(f"generation_id={GENERATION}" in error for error in step["errors"])
            assert facts.secret not in json.dumps(step)
            saved = await TransactionalSaver(reopened).aget_tuple({"configurable": {"thread_id": agent[1]}})
            assert saved is not None
            errors = saved.checkpoint["channel_values"]["errors"]
            assert any(f"generation_id={GENERATION}" in error for error in errors)
            assert facts.secret not in json.dumps(errors)
        assert calls == ["/api/v1/chat/completions"]
    finally:
        await provider.aclose()
