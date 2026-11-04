"""Actual PG/provider composition: reserve key without Studio or historic totals."""

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
from app.llm.roles import select

pytestmark = pytest.mark.integration
BASE = "https://accounting.invalid/v1"
BALANCES = {"GigaChat-Ultra": 100, "GigaChat-Pro": 200, "GigaChat": 300}
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture
async def reserve(migrated_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    dsn = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        row = await (
            await conn.execute(
                "insert into llm_profiles(code,provider,model,role,temperature,rpd_limit,is_active) "
                "values(%s,'gigachat','GigaChat-3-Ultra','main',0.15,4,true) returning *",
                ("api-reserve-" + uuid.uuid4().hex,),
            )
        ).fetchone()
    settings = get_settings().model_copy(update={"llm_provider": "gigachat"})
    profile = select(settings, [row], {"main_profile_id": row["id"]})["main"]
    service = PostgresAccounting()
    keys = [ApiKey(label=str(i), secret="synthetic-" + row["code"] + str(i), tokens_limit=100) for i in range(2)]
    facts = [KeyFacts("gigachat", key.secret, BASE, 100) for key in keys]
    calls = []
    state = {"balance": BALANCES.copy(), "missing_usage": False, "status": 200}

    def http(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/oauth":
            slot = next(i for i, key in enumerate(keys) if request.headers["authorization"] == "Basic " + key.secret)
            return httpx.Response(
                200,
                json={
                    "access_token": f"synthetic-token-{slot}",
                    "expires_at": int((dt.datetime.now(dt.UTC).timestamp() + 3600) * 1000),
                },
            )
        if request.url.path == "/v1/balance":
            balances = state["balance"]
            if state.get("exhausted_slot") == request.headers["authorization"]:
                balances = {**balances, "GigaChat-Ultra": 0}
            return httpx.Response(
                state["status"],
                json={"balance": [{"usage": name, "value": value} for name, value in balances.items()]},
            )
        assert request.url.path == "/v1/chat/completions"
        if state.get("chat_timeout"):
            raise httpx.ReadTimeout("synthetic", request=request)
        payload = json.loads(request.content)
        usage = None if state["missing_usage"] else {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        body = {
            "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok":true}'}}
            ],
            "usage": usage,
        }
        if payload.get("stream"):
            return httpx.Response(
                200,
                text="data: "
                + json.dumps({"choices": [{"delta": {"content": "ok"}}], "usage": usage})
                + "\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=body)

    def provider(selected=None):
        return GigaChatProvider(
            KeyPool(selected or keys),
            oauth_url="https://accounting.invalid/oauth",
            base_url=BASE,
            transport=httpx.MockTransport(http),
        )

    return profile, service, facts, keys, calls, state, provider, dsn


async def test_connect_preserves_shared_profile_cap_and_cannot_reset_usage(reserve):
    profile, service, facts, keys, calls, state, make, dsn = reserve
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        now = (await (await conn.execute("select clock_timestamp() as value")).fetchone())["value"]
    await service.reconcile(
        profile,
        facts[0],
        reconciliation_id=uuid.uuid4(),
        as_of=now,
        tokens_used=11,
        requests_today=2,
        profile_requests={f"id:{profile.id}": 2},
        confirmed=True,
        acknowledge_unknown_origin=True,
    )
    result = await service.connect_gigachat(profile, facts[1], BALANCES, confirmed=True)
    assert result["admission_allowed"] and result["tokens_used"] == 0
    assert result["historical_usage_known"] is False and result["profile_requests_today"] == 2
    provider = make([keys[1]])
    try:
        obj, usage, _ = await provider.complete_structured(
            [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
        )
        assert obj == {"ok": True} and usage.total_tokens == 5
    finally:
        await provider.aclose()
    result = await service.connect_gigachat(profile, facts[1], BALANCES, confirmed=True)
    assert result["state"] == "existing_app_origin" and result["tokens_used"] == 5
    assert result["requests_today"] == 1 and result["profile_requests_today"] == 3
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        row = await (
            await conn.execute(
                "select historical_usage_known,observation from llm_runtime.gigachat_app_origins where observation->'balances'=%s::jsonb",
                (json.dumps(BALANCES),),
            )
        ).fetchone()
    assert row["historical_usage_known"] is False
    assert row["observation"]["scope"] == "application_since_origin"
    assert any(path == "/v1/balance" for _, path, _ in calls)


async def test_unknown_attempt_cannot_be_cleared_by_reconnect_or_provider_balance(reserve):
    profile, service, facts, keys, calls, state, make, _ = reserve
    await service.connect_gigachat(profile, facts[0], BALANCES, confirmed=True)
    state["missing_usage"] = True
    provider = make([keys[0]])
    try:
        with pytest.raises(ProviderError, match="расход"):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
        before = list(calls)
        result = await service.connect_gigachat(profile, facts[0], BALANCES, confirmed=True)
        assert not result["admission_allowed"] and result["requests_today"] == 1
        with pytest.raises(ProviderError, match="reconciliation"):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
        assert calls == before
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "status,balances", [(200, {"GigaChat-Ultra": 0}), (200, {"GigaChat-Pro": 999}), (403, BALANCES), (500, BALANCES)]
)
async def test_bad_or_exhausted_provider_balance_never_reserves_inference(reserve, status, balances):
    profile, service, facts, keys, calls, state, make, _ = reserve
    await service.connect_gigachat(profile, facts[0], BALANCES, confirmed=True)
    state.update(status=status, balance=balances)
    provider = make([keys[0]])
    try:
        with pytest.raises(ProviderError):
            await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
    finally:
        await provider.aclose()
    snapshot = await service.snapshot(profile, facts[0], timeout_s=5)
    assert snapshot.requests_today == snapshot.tokens_used == 0
    assert not any(path == "/v1/chat/completions" for _, path, _ in calls)


async def test_stream_and_provider_restart_preserve_app_usage_and_cap(reserve):
    profile, service, facts, keys, calls, state, make, _ = reserve
    await service.connect_gigachat(profile, facts[1], BALANCES, confirmed=True)
    for expected in [5, 10, 15, 20]:
        provider = make([keys[1]])
        try:
            assert [
                chunk
                async for chunk in provider.stream(
                    [{"role": "user", "content": "Synthetic ping"}], profile, timeout_s=5
                )
            ] == ["ok"]
        finally:
            await provider.aclose()
        snapshot = await service.snapshot(profile, facts[1], timeout_s=5)
        assert snapshot.tokens_used == expected and snapshot.requests_today == expected // 5
    before = list(calls)
    provider = make([keys[1]])
    try:
        with pytest.raises(ProviderError, match="суточный"):
            _ = [
                chunk
                async for chunk in provider.stream(
                    [{"role": "user", "content": "Synthetic ping"}], profile, timeout_s=5
                )
            ]
        assert calls == before
    finally:
        await provider.aclose()


async def test_connect_rejects_existing_usage_and_unknown_origin_without_confirmation(reserve):
    profile, service, facts, keys, calls, state, make, _ = reserve
    with pytest.raises(ProviderError):
        await service.connect_gigachat(profile, facts[0], BALANCES)
    # An admitted attempt is durable even if no HTTP response was observed.
    await service.connect_gigachat(profile, facts[0], BALANCES, confirmed=True)
    async with service.key_scope(profile, facts[0], timeout_s=5) as scope:
        async with scope.inference():
            pass
    result = await service.connect_gigachat(profile, facts[0], BALANCES, confirmed=True)
    assert not result["admission_allowed"] and result["requests_today"] == 1


@pytest.mark.parametrize("streaming", [False, True])
async def test_native_pool_rotates_to_reserve_without_spending_first_key(reserve, streaming):
    profile, service, facts, keys, calls, state, make, _ = reserve
    for fact in facts:
        await service.connect_gigachat(profile, fact, BALANCES, confirmed=True)
    state["exhausted_slot"] = "Bearer synthetic-token-0"
    provider = make()
    try:
        if streaming:
            assert [
                chunk
                async for chunk in provider.stream(
                    [{"role": "user", "content": "Synthetic ping"}], profile, timeout_s=5
                )
            ] == ["ok"]
        else:
            obj, usage, _ = await provider.complete_structured(
                [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
            )
            assert obj == {"ok": True}
        assert [(method, auth) for method, path, auth in calls if path == "/v1/chat/completions"] == [
            ("POST", "Bearer synthetic-token-1")
        ]
    finally:
        await provider.aclose()
    first = await service.snapshot(profile, facts[0], timeout_s=5)
    second = await service.snapshot(profile, facts[1], timeout_s=5)
    assert first.tokens_used == first.requests_today == 0
    assert second.tokens_used == 5 and second.requests_today == 1
    assert first.profile_requests_today == second.profile_requests_today == 1


@pytest.mark.parametrize("field,value", [("confirmed_tokens", 7), ("legacy_tokens_hint", 3), ("usage_known", True)])
async def test_existing_accounting_basis_is_never_overwritten(reserve, field, value):
    profile, service, facts, keys, calls, state, make, dsn = reserve
    await service.snapshot(profile, facts[0], timeout_s=5)
    from psycopg import sql

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            sql.SQL("update llm_runtime.credentials set {}=%s where verifier=%s").format(sql.Identifier(field)),
            (value, facts[0].verifier()),
        )
    with pytest.raises(ProviderError, match="reconciliation"):
        await service.connect_gigachat(profile, facts[0], BALANCES, confirmed=True)


async def test_cli_connect_reads_metadata_without_inference_or_raw_secret_output(reserve, monkeypatch):
    from app.llm import accounting_cli

    profile, service, facts, keys, calls, state, make, _ = reserve
    metadata = []

    async def selection(args):
        return profile, facts[1]

    async def balance(self, key, chosen_profile, *, timeout_s):
        metadata.append("balance")
        return BALANCES.copy()

    monkeypatch.setattr(accounting_cli, "selection", selection)
    monkeypatch.setattr(GigaChatProvider, "fetch_balance", balance)
    args = accounting_cli.parser().parse_args(
        ["connect-gigachat", "--profile-id", str(profile.id), "--env-slot", "gigachat2"]
    )
    with pytest.raises(ProviderError):
        await accounting_cli.execute(args)
    assert metadata == []
    args.confirm = True
    result = await accounting_cli.execute(args)
    assert metadata == ["balance"] and calls == []
    assert result["admission_allowed"] and not result["historical_usage_known"]
    assert keys[1].secret not in json.dumps(result, default=str)


@pytest.mark.parametrize("streaming", [False, True])
async def test_unknown_inference_is_not_replayed_on_reserve_within_the_same_pool_call(reserve, streaming):
    profile, service, facts, keys, calls, state, make, _ = reserve
    for fact in facts:
        await service.connect_gigachat(profile, fact, BALANCES, confirmed=True)
    state["chat_timeout"] = True
    provider = make()
    try:
        with pytest.raises(ProviderError) as caught:
            if streaming:
                _ = [
                    part
                    async for part in provider.stream(
                        [{"role": "user", "content": "Synthetic ping"}], profile, timeout_s=5
                    )
                ]
            else:
                await provider.complete_structured(
                    [{"role": "user", "content": "Synthetic ping"}], SCHEMA, profile, timeout_s=5
                )
        assert caught.value.kind == "timeout"
        assert len([x for x in calls if x[1] == "/v1/chat/completions"]) == 1
    finally:
        await provider.aclose()
    first = await service.snapshot(profile, facts[0], timeout_s=5)
    second = await service.snapshot(profile, facts[1], timeout_s=5)
    assert not first.usage_known and first.requests_today == 1
    assert second.usage_known and second.requests_today == 0
