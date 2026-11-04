"""T-050: synthetic private ledger; no actual provider calls or production data."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import get_settings
from app.llm.accounting import KeyFacts, PostgresAccounting, Ticket, _utc_now
from app.llm.base import LLMProfile, ProviderError

pytestmark = pytest.mark.integration


@pytest.fixture
async def accounting_case(migrated_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    profile = LLMProfile(code=f"quota-{uuid.uuid4().hex}", provider="gigachat", model="synthetic", rpd_limit=2)
    facts = KeyFacts("gigachat", f"synthetic-credential-{uuid.uuid4().hex}", "https://synthetic.invalid/v1", 20, 2)
    return PostgresAccounting(), profile, facts


async def now():
    from app.db.session import psycopg_dsn

    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True, row_factory=dict_row) as conn:
        return await _utc_now(conn)


async def confirm(case, *, tokens=0, requests=0, reconciliation_id=None):
    service, profile, facts = case
    return await service.reconcile(
        profile,
        facts,
        reconciliation_id=reconciliation_id or uuid.uuid4(),
        as_of=await now(),
        tokens_used=tokens,
        requests_today=requests,
        profile_requests={f"code:{profile.code}": requests},
        confirmed=True,
        acknowledge_unknown_origin=True,
    )


async def test_registration_is_unknown_and_never_auto_known_zero(accounting_case):
    service, profile, facts = accounting_case
    with pytest.raises(ProviderError, match="reconciliation"):
        async with service.key_scope(profile, facts, timeout_s=3):
            pytest.fail("unknown budget must not permit a wire")
    async with service.key_scope(profile, facts, timeout_s=3, check_budget=False) as scope:
        row = await (
            await scope.conn.execute(
                "select usage_known,confirmed_tokens from llm_runtime.credentials where uid=%s", (scope.uid,)
            )
        ).fetchone()
        assert row == {"usage_known": False, "confirmed_tokens": 0}
        assert await (
            await scope.conn.execute(
                "select count(*) as n from llm_runtime.wire_attempts where credential_uid=%s", (scope.uid,)
            )
        ).fetchone() == {"n": 0}


async def test_reconciliation_is_explicit_idempotent_and_reservation_cannot_resend(accounting_case):
    service, profile, facts = accounting_case
    rid = uuid.uuid4()
    as_of = await now()
    kwargs = dict(
        reconciliation_id=rid,
        as_of=as_of,
        tokens_used=0,
        requests_today=0,
        profile_requests={f"code:{profile.code}": 0},
        confirmed=True,
        acknowledge_unknown_origin=True,
    )
    first = await service.reconcile(profile, facts, **kwargs)
    second = await service.reconcile(profile, facts, **kwargs)
    assert first["id"] == second["id"] == str(rid)
    assert not first["idempotent"] and second["idempotent"]
    attempt_id = uuid.uuid4()
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit(attempt_id)
        await ticket.observe(2, 3, final=True)
        await ticket.observe(2, 3, final=True)
        await Ticket(scope, attempt_id).unknown("network")
        with pytest.raises(ProviderError, match="повтор"):
            await scope.admit(attempt_id)
        day = await (
            await scope.conn.execute(
                "select requests_today from llm_runtime.daily_usage where scope_type='key' and scope_id=%s",
                (str(scope.uid),),
            )
        ).fetchone()
        assert day == {"requests_today": 1}
        account = await (
            await scope.conn.execute(
                "select confirmed_tokens,usage_known from llm_runtime.credentials where uid=%s", (scope.uid,)
            )
        ).fetchone()
        assert account == {"confirmed_tokens": 5, "usage_known": True}


async def test_new_connection_keeps_actual_daily_cap_and_known_usage(accounting_case):
    await confirm(accounting_case)
    service, profile, facts = accounting_case
    for _ in range(2):
        async with PostgresAccounting().key_scope(profile, facts, timeout_s=3) as scope:
            ticket = await scope.admit()
            await ticket.observe(1, 2, final=True)
    with pytest.raises(ProviderError) as rejected:
        async with service.key_scope(profile, facts, timeout_s=3):
            pytest.fail("N+1 must not reach the provider")
    assert rejected.value.kind == "rate_limit"


async def test_wire_failure_charges_once_and_unknown_blocks_next_budgeted_call(accounting_case):
    await confirm(accounting_case)
    service, profile, facts = accounting_case
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit()
        await ticket.observe(1, 1)
        await ticket.unknown("rate_limit")
        await Ticket(scope, ticket.id).unknown("rate_limit")
        account = await (
            await scope.conn.execute(
                "select confirmed_tokens,usage_known from llm_runtime.credentials where uid=%s", (scope.uid,)
            )
        ).fetchone()
        assert account == {"confirmed_tokens": 2, "usage_known": False}
        day = await (
            await scope.conn.execute(
                "select requests_today from llm_runtime.daily_usage where scope_type='key' and scope_id=%s",
                (str(scope.uid),),
            )
        ).fetchone()
        assert day == {"requests_today": 1}
    with pytest.raises(ProviderError, match="reconciliation"):
        async with service.key_scope(profile, facts, timeout_s=3):
            pytest.fail("unknown usage cannot silently mean zero")
    with pytest.raises(ProviderError, match="token floor"):
        await confirm(accounting_case, tokens=1, requests=1)
    await confirm(accounting_case, tokens=2, requests=1)
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        second = await scope.admit()
        await second.observe(0, 0, final=True)


async def test_snapshot_never_turns_unknown_into_remaining_zero(accounting_case):
    service, profile, facts = accounting_case
    before = await service.snapshot(profile, facts, timeout_s=3)
    assert not before.usage_known and not before.requests_known
    assert before.tokens_remaining is None and before.requests_remaining is None
    assert before.refusal is not None
    public = before.public()
    assert not {"uid", "verifier", "secret", "refusal"} & public.keys()
    assert facts.secret not in str(public)
    await confirm(accounting_case)
    after = await service.snapshot(profile, facts, timeout_s=3)
    assert after.usage_known and after.requests_known
    assert after.tokens_remaining == 20 and after.requests_remaining == 2
    assert after.refusal is None


async def test_parallel_connections_cannot_overshoot_global_profile_cap(accounting_case):
    import asyncio
    from dataclasses import replace

    service, profile, first = accounting_case
    second = replace(first, secret=f"synthetic-other-{uuid.uuid4().hex}")
    await confirm((service, profile, first))
    await confirm((service, profile, second))
    admitted = []

    async def caller(facts):
        try:
            async with PostgresAccounting().key_scope(profile, facts, timeout_s=10) as scope:
                ticket = await scope.admit()
                admitted.append(ticket.id)
                await ticket.observe(1, 1, final=True)
            return None
        except ProviderError as exc:
            return exc.kind

    results = await asyncio.gather(*(caller(first if n % 2 else second) for n in range(12)))
    assert len(admitted) == 2 and len(set(admitted)) == 2
    assert results.count(None) == 2 and set(results) <= {None, "rate_limit"}
    async with service.key_scope(profile, first, timeout_s=3, check_budget=False) as scope:
        day = await (
            await scope.conn.execute(
                "select requests_today from llm_runtime.daily_usage where scope_type='profile' and scope_id=%s",
                (f"code:{profile.code}",),
            )
        ).fetchone()
        assert day == {"requests_today": 2}


async def test_cumulative_observations_and_late_reconciled_data_never_double_count(accounting_case):
    service, profile, facts = accounting_case
    await confirm(accounting_case)
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit()
        await ticket.observe(1, 1)
        await ticket.observe(1, 1)
        await ticket.observe(1, 2)
        await ticket.unknown("network")
        attempt_id = ticket.id
    await confirm(accounting_case, tokens=5, requests=1)
    async with service.key_scope(profile, facts, timeout_s=3, check_budget=False) as scope:
        replay = Ticket(scope, attempt_id)
        await replay.observe(1, 4, final=True)
        await replay.observe(1, 4, final=True)
        row = await (
            await scope.conn.execute(
                "select confirmed_tokens,usage_known from llm_runtime.credentials where uid=%s", (scope.uid,)
            )
        ).fetchone()
        assert row == {"confirmed_tokens": 5, "usage_known": False}
        day = await (
            await scope.conn.execute(
                "select requests_today from llm_runtime.daily_usage where scope_type='key' and scope_id=%s",
                (str(scope.uid),),
            )
        ).fetchone()
        assert day == {"requests_today": 1}
    with pytest.raises(ProviderError, match="reconciliation"):
        async with service.key_scope(profile, facts, timeout_s=3):
            pytest.fail("new late facts must not silently certify reconciliation")


async def test_profile_identity_survives_rename_but_reused_id_is_unknown(accounting_case):
    from dataclasses import replace

    from app.api.settings import public_profile
    from app.db.session import psycopg_dsn
    from app.sim import baseline_llm

    service, template, facts = accounting_case
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True, row_factory=dict_row) as conn:
        original = await (
            await conn.execute(
                "insert into llm_profiles(code,provider,model,role,rpd_limit) values(%s,'gigachat','synthetic','main',2) returning *",
                (template.code,),
            )
        ).fetchone()
        profile = replace(template, id=original["id"])
        assert "quota_uid" not in public_profile(dict(original))
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as fingerprint_conn:
            before = await baseline_llm.read(fingerprint_conn)
        await service.reconcile(
            profile,
            facts,
            reconciliation_id=uuid.uuid4(),
            as_of=await now(),
            tokens_used=0,
            requests_today=0,
            profile_requests={f"id:{profile.id}": 0},
            confirmed=True,
            acknowledge_unknown_origin=True,
        )
        async with service.key_scope(profile, facts, timeout_s=3) as scope:
            ticket = await scope.admit()
            await ticket.observe(1, 1, final=True)
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as fingerprint_conn:
            assert await baseline_llm.read(fingerprint_conn) == before  # Operational counters are excluded.
        await conn.execute(
            "update llm_profiles set code=%s,rpd_limit=1 where id=%s", (f"{template.code}-renamed", profile.id)
        )
        renamed = await (await conn.execute("select quota_uid from llm_profiles where id=%s", (profile.id,))).fetchone()
        assert renamed["quota_uid"] == original["quota_uid"]
        # Frozen profile values cannot restore the larger current daily allowance.
        with pytest.raises(ProviderError) as refused:
            async with service.key_scope(profile, facts, timeout_s=3):
                pytest.fail("rename/limit edits must retain the already spent profile quota")
        assert refused.value.kind == "rate_limit"
        await conn.execute("delete from llm_profiles where id=%s", (profile.id,))
        replacement = await (
            await conn.execute(
                "insert into llm_profiles(id,code,provider,model,role,rpd_limit) overriding system value values(%s,%s,'gigachat','synthetic','main',2) returning quota_uid",
                (profile.id, f"{template.code}-replacement"),
            )
        ).fetchone()
        assert replacement["quota_uid"] != original["quota_uid"]
        with pytest.raises(ProviderError, match="reconciliation"):
            async with service.key_scope(profile, facts, timeout_s=3):
                pytest.fail("numeric ID reuse must not inherit known quota from a different configuration")
        old_counter = await (
            await conn.execute(
                "select requests_today from llm_runtime.daily_usage where scope_type='profile' and scope_id=%s",
                (f"quota:{original['quota_uid']}",),
            )
        ).fetchone()
        assert old_counter["requests_today"] == 1


async def test_private_profile_identity_is_config_fingerprint_input(accounting_case):
    from app.db.session import psycopg_dsn
    from app.sim import baseline_llm

    _, profile, _ = accounting_case
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        row = await (
            await conn.execute(
                "insert into llm_profiles(code,provider,model,role) values(%s,'gigachat','synthetic','main') returning id,quota_uid",
                (profile.code,),
            )
        ).fetchone()
        before = await baseline_llm.read(conn)
        await conn.execute("update llm_profiles set quota_uid=gen_random_uuid() where id=%s", (row[0],))
        assert await baseline_llm.read(conn) != before


async def test_bank_dump_restore_preserves_private_quota_and_profile_identity(seeded, monkeypatch, tmp_path):
    import subprocess
    from dataclasses import replace

    from app.db.session import psycopg_dsn
    from app.sim import baseline

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path / "runs")
    service = PostgresAccounting()
    code = f"quota-{uuid.uuid4().hex}"
    facts = KeyFacts("gigachat", f"synthetic-restore-{uuid.uuid4().hex}", "https://synthetic.invalid/v1", 20, 3)
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        row = await (
            await conn.execute(
                "insert into llm_profiles(code,provider,model,role,rpd_limit) values(%s,'gigachat','synthetic','bench_only',3) returning id,quota_uid",
                (code,),
            )
        ).fetchone()
    profile = LLMProfile(id=row[0], code=code, provider="gigachat", model="synthetic", role="bench_only", rpd_limit=3)
    await service.reconcile(
        profile,
        facts,
        reconciliation_id=uuid.uuid4(),
        as_of=await now(),
        tokens_used=0,
        requests_today=0,
        profile_requests={f"id:{profile.id}": 0},
        confirmed=True,
        acknowledge_unknown_origin=True,
    )
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=False) as conn:
        await baseline.dump(conn, profile="lite")
        await conn.commit()
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit()
        await ticket.observe(2, 3, final=True)
    listing = subprocess.run(
        ["pg_restore", "--list", str(tmp_path / "lite.dump")], capture_output=True, text=True, check=True
    )
    assert "llm_runtime" not in listing.stdout
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=False) as conn:
        await baseline.restore(conn, profile="lite")
    after = await service.snapshot(profile, facts, timeout_s=3)
    assert after.tokens_used == 5 and after.requests_today == 1
    assert after.usage_known and after.requests_known
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        restored = await (
            await conn.execute("select quota_uid from llm_profiles where id=%s", (profile.id,))
        ).fetchone()
        assert restored[0] == row[1]
    assert (await service.snapshot(replace(profile, code=f"{code}-frozen"), facts, timeout_s=3)).requests_today == 1


async def test_equal_physical_aliases_share_cap_and_conflicting_limits_fail_closed(accounting_case):
    import asyncio
    from dataclasses import replace

    from app.db.session import psycopg_dsn

    service, template, facts = accounting_case
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        ids = []
        for label in ("alias-a", "alias-b"):
            row = await (
                await conn.execute(
                    "insert into llm_api_keys(provider,label,encrypted_key,tokens_limit,rpd_limit,endpoint_url,scope) "
                    "values('gigachat',%s,pgp_sym_encrypt(%s,%s),20,2,%s,%s) returning id",
                    (label, facts.secret, get_settings().app_secret, facts.endpoint, get_settings().gigachat_scope),
                )
            ).fetchone()
            ids.append(row[0])
        first = replace(template, api_key_id=ids[0], base_url=facts.endpoint)
        second = replace(template, api_key_id=ids[1], base_url=facts.endpoint)
        await confirm((service, first, facts))

        async def caller(profile):
            try:
                async with service.key_scope(profile, facts, timeout_s=5) as scope:
                    ticket = await scope.admit()
                    await ticket.observe(1, 1, final=True)
                return "admitted"
            except ProviderError as exc:
                return exc.kind

        results = await asyncio.gather(*(caller(first if i % 2 else second) for i in range(8)))
        assert results.count("admitted") == 2 and set(results) <= {"admitted", "rate_limit"}
        await conn.execute("update llm_api_keys set tokens_limit=21 where id=%s", (ids[1],))
        with pytest.raises(ProviderError, match="конфликтующие лимиты"):
            async with service.key_scope(first, facts, timeout_s=3):
                pytest.fail("a second alias must not silently change the effective budget")
        # Deactivation removes the conflicting config, but cannot refund spent requests.
        await conn.execute("update llm_api_keys set is_active=false where id=%s", (ids[1],))
        with pytest.raises(ProviderError) as exhausted:
            async with service.key_scope(first, facts, timeout_s=3):
                pytest.fail("deactivation must not reset the shared ledger")
        assert exhausted.value.kind == "rate_limit"


async def test_daily_rollover_uses_db_utc_after_contended_locks(accounting_case, monkeypatch):
    import asyncio
    import datetime as dt

    from app.db.session import psycopg_dsn
    from app.llm import accounting, credentials

    service, profile, facts = accounting_case
    await confirm(accounting_case)
    previous = await now()
    next_day = dt.datetime.combine(previous.date() + dt.timedelta(days=1), dt.time(0, 0, 1), dt.UTC)
    clock_reads = []
    chosen = previous

    async def clock(conn):
        clock_reads.append(chosen)
        return chosen

    monkeypatch.setattr(accounting, "_utc_now", clock)
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as blocker:
        async with blocker.transaction():
            await blocker.execute("select pg_advisory_xact_lock(%s)", (credentials.LOCK,))
            task = asyncio.create_task(service.snapshot(profile, facts, timeout_s=5))
            # Observe the actual DB waiter, not a guessed sleep duration.
            async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as observer:
                async with asyncio.timeout(3):
                    while True:
                        waiting = await (
                            await observer.execute(
                                "select exists(select 1 from pg_locks where locktype='advisory' and not granted and database=(select oid from pg_database where datname=current_database()))"
                            )
                        ).fetchone()
                        if waiting[0]:
                            break
                        await asyncio.sleep(0)
            assert not clock_reads
            chosen = next_day
        result = await task
    assert clock_reads == [next_day]
    assert result.requests_day == next_day.date()
    assert result.requests_today == 0 and result.requests_known
    for _ in range(2):
        async with service.key_scope(profile, facts, timeout_s=3) as scope:
            ticket = await scope.admit()
            await ticket.observe(1, 1, final=True)
    with pytest.raises(ProviderError) as exhausted:
        async with service.key_scope(profile, facts, timeout_s=3):
            pytest.fail("UTC rollover must not allow N+1")
    assert exhausted.value.kind == "rate_limit"


async def test_unfinished_reservation_requires_expired_deadline_and_explicit_reconciliation(accounting_case):

    from app.db.session import psycopg_dsn

    service, profile, facts = accounting_case
    await confirm(accounting_case)
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit()
        attempt_id = ticket.id  # Simulate process death after durable reservation.
    with pytest.raises(ProviderError, match="reconciliation"):
        async with service.key_scope(profile, facts, timeout_s=3):
            pytest.fail("a lost process cannot silently refund its reservation")
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        await conn.execute(
            "update llm_runtime.wire_attempts set deadline_at=clock_timestamp()-interval '1 second' where id=%s",
            (attempt_id,),
        )
    with pytest.raises(ProviderError, match="acknowledge"):
        await confirm(accounting_case, requests=1)
    await service.reconcile(
        profile,
        facts,
        reconciliation_id=uuid.uuid4(),
        as_of=await now(),
        tokens_used=0,
        requests_today=1,
        profile_requests={f"code:{profile.code}": 1},
        confirmed=True,
        acknowledge_unknown_origin=True,
        acknowledge_orphans=True,
    )
    after = await service.snapshot(profile, facts, timeout_s=3)
    assert after.usage_known and after.requests_today == 1
    assert after.requests_remaining == 1


async def test_profile_private_identity_never_enters_public_or_ar_projections(seeded, monkeypatch):
    import json

    from fastapi import HTTPException

    from app.api import engine, settings
    from app.db.session import psycopg_dsn
    from app.llm.run_profiles import capture

    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        profile_id, private_uid = await (
            await conn.execute(
                "insert into llm_profiles(code,provider,model,role) values(%s,'gigachat','synthetic','main') returning id,quota_uid",
                (f"projection-{uuid.uuid4().hex}",),
            )
        ).fetchone()
        snapshot = await capture(conn, profile_id)
    profiles = await settings.get_llm_profiles()
    exported = await settings.get_settings_export()
    for projection in (snapshot, profiles, exported):
        rendered = json.dumps(projection, default=str)
        assert "quota_uid" not in rendered and str(private_uid) not in rendered
    assert snapshot["profile_ids"]["main"] == profile_id
    assert "llm_profiles" not in engine.DB_ALLOW
    assert not any(name.startswith("llm_runtime") for name in engine.DB_ALLOW)
    for name in ("llm_profiles", "llm_runtime.credentials", "llm_runtime.wire_attempts"):
        with pytest.raises(HTTPException) as denied:
            await engine.get_engine_db_tables_name_rows(name)
        assert denied.value.status_code == 403


async def test_unknown_origin_ack_and_legacy_hint_provenance_are_explicit(accounting_case):
    from dataclasses import replace

    from app.db.session import psycopg_dsn

    service, template, facts = accounting_case
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        key_id = (
            await (
                await conn.execute(
                    "insert into llm_api_keys(provider,label,encrypted_key,tokens_used,tokens_limit,rpd_limit,endpoint_url,scope) "
                    "values('gigachat','legacy-hint',pgp_sym_encrypt(%s,%s),20,20,2,%s,%s) returning id",
                    (facts.secret, get_settings().app_secret, facts.endpoint, get_settings().gigachat_scope),
                )
            ).fetchone()
        )[0]
        profile = replace(template, api_key_id=key_id, base_url=facts.endpoint)
        before = await service.snapshot(profile, facts, timeout_s=3)
        assert not before.usage_known and before.tokens_used == 0 and before.tokens_remaining is None
        with pytest.raises(ProviderError, match="unknown origin"):
            await service.reconcile(
                profile,
                facts,
                reconciliation_id=uuid.uuid4(),
                as_of=await now(),
                tokens_used=0,
                requests_today=0,
                confirmed=True,
            )
        receipt = await confirm((service, profile, facts))
        audit = (
            await (
                await conn.execute(
                    "select observation from llm_runtime.reconciliations where id=%s", (uuid.UUID(receipt["id"]),)
                )
            ).fetchone()
        )[0]
        assert audit["legacy_tokens_hint"] == 20 and not audit["prior_usage_known"]
        assert audit["prior_usage_source"] == "unknown"
        assert audit["request"]["acknowledge_unknown_origin"] is True
        assert facts.secret not in str(audit)
        after = await service.snapshot(profile, facts, timeout_s=3)
        assert after.usage_known and after.tokens_used == 0 and after.tokens_remaining == 20


async def test_gigachat_counts_inference_repair_but_not_oauth(accounting_case):
    import httpx

    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool

    service, profile, facts = accounting_case
    await confirm(accounting_case)
    requests = []

    def fake(request):
        requests.append(request.url.path)
        if request.url.path == "/oauth":
            return httpx.Response(200, json={"access_token": "synthetic-access", "expires_at": 9999999999999})
        return httpx.Response(
            200,
            json={
                "model": profile.model,
                "choices": [
                    {"message": {"content": '{"x":1}' if requests.count("/v1/chat/completions") == 2 else "{}"}}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )

    key = ApiKey("synthetic", facts.secret, tokens_limit=20)
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://synthetic.invalid/oauth",
        base_url=facts.endpoint,
        transport=httpx.MockTransport(fake),
    )
    try:
        result, usage, _ = await provider.complete_structured(
            [], {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}, profile, timeout_s=5
        )
        assert result == {"x": 1} and usage.total_tokens == 6 and usage.request_count == 2
        assert requests == ["/oauth", "/v1/chat/completions", "/v1/chat/completions"]
        observed = await service.snapshot(profile, facts, timeout_s=3)
        assert observed.tokens_used == 6 and observed.requests_today == 2 and observed.usage_known
        assert key.tokens_used == 6  # Outer structured parser must not double-account.
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "status,usage_payload,expected",
    [
        (503, None, "unavailable"),
        (200, None, "bad_output"),
        (200, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, None),
        (400, None, "quota"),
    ],
)
async def test_sdk_wire_failures_unknown_and_validated_zero(accounting_case, status, usage_payload, expected):
    from dataclasses import replace

    import httpx

    from app.llm.openai_compat import OpenAICompatProvider

    service, original, original_facts = accounting_case
    profile = replace(original, provider="openai_compatible")
    facts = replace(original_facts, provider="openai_compatible")
    await confirm((service, profile, facts))
    requests = []

    def fake(request):
        requests.append(request.url.path)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "synthetic failure"}})
        response = {
            "id": "synthetic",
            "object": "chat.completion",
            "created": 1,
            "model": profile.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"x":1}'}, "finish_reason": "stop"}],
        }
        if usage_payload is not None:
            response["usage"] = usage_payload
        return httpx.Response(200, json=response)

    provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(fake))
    try:
        if expected is not None:
            with pytest.raises(ProviderError) as rejected:
                await provider.complete_structured([], {"type": "object"}, profile, timeout_s=5)
            # A native-schema400 makes the first attempt unknown; the alternate
            # format cannot bypass the unknown profile budget and never reaches HTTP.
            assert rejected.value.kind == expected and rejected.value.usage is None
        else:
            result, usage, _ = await provider.complete_structured([], {"type": "object"}, profile, timeout_s=5)
            assert result == {"x": 1} and usage.total_tokens == 0
        assert requests == ["/v1/chat/completions"]
        observed = await service.snapshot(profile, facts, timeout_s=3)
        assert observed.requests_today == 1 and observed.tokens_used == 0
        assert observed.usage_known is (expected is None)
    finally:
        await provider.aclose()


@pytest.mark.parametrize("provider_name", ["gigachat", "openai_compatible"])
@pytest.mark.parametrize("mode", ["cumulative", "missing", "cancel"])
async def test_stream_accounts_once_cumulative_unknown_or_consumer_close(accounting_case, provider_name, mode):
    import json
    from dataclasses import replace

    import httpx

    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool
    from app.llm.openai_compat import OpenAICompatProvider

    service, original, original_facts = accounting_case
    profile = replace(original, provider=provider_name)
    facts = replace(original_facts, provider=provider_name)
    await confirm((service, profile, facts))
    requests = []

    def fake(request):
        requests.append(request.url.path)
        frames = [
            {
                "id": "synthetic",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": profile.model,
                "choices": [{"index": 0, "delta": {"content": "plain-prefix"}, "finish_reason": None}],
            }
        ]
        if mode == "cumulative":
            for prompt, completion in [(1, 1), (1, 1), (1, 3)]:
                frames.append(
                    {
                        "id": "synthetic",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": profile.model,
                        "choices": [],
                        "usage": {
                            "prompt_tokens": prompt,
                            "completion_tokens": completion,
                            "total_tokens": prompt + completion,
                        },
                    }
                )
        payload = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
        return httpx.Response(200, content=payload, headers={"Content-Type": "text/event-stream"})

    if provider_name == "gigachat":
        key = ApiKey(
            "synthetic", facts.secret, tokens_limit=20, access_token="synthetic-access", token_expires_at=9999999999
        )
        provider = GigaChatProvider(
            KeyPool([key]),
            oauth_url="https://synthetic.invalid/oauth",
            base_url=facts.endpoint,
            transport=httpx.MockTransport(fake),
        )
    else:
        provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(fake))
    iterator = provider.stream([], profile, timeout_s=5)
    try:
        if mode == "cancel":
            assert await anext(iterator) == "plain-prefix"
            await iterator.aclose()
        elif mode == "missing":
            chunks = []
            with pytest.raises(ProviderError) as error:
                async for chunk in iterator:
                    chunks.append(chunk)
            assert chunks == ["plain-prefix"] and error.value.usage is None
        else:
            assert "".join([chunk async for chunk in iterator]) == "plain-prefix"
        observed = await service.snapshot(profile, facts, timeout_s=3)
        assert requests == ["/v1/chat/completions"]
        assert observed.requests_today == 1
        assert observed.tokens_used == (4 if mode == "cumulative" else 0)
        assert observed.usage_known is (mode == "cumulative")
    finally:
        await iterator.aclose()
        await provider.aclose()


async def test_durable_quota_health_never_fabricates_spent_tokens(accounting_case):
    import httpx

    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool

    service, profile, facts = accounting_case
    await confirm(accounting_case)
    requests = []

    def fake(request):
        requests.append(request.url.path)
        return httpx.Response(403, json={"error": "quota"})

    key = ApiKey(
        "synthetic", facts.secret, tokens_limit=20, access_token="synthetic-access", token_expires_at=9999999999
    )
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://synthetic.invalid/oauth",
        base_url=facts.endpoint,
        transport=httpx.MockTransport(fake),
    )
    try:
        for _ in range(2):
            with pytest.raises(ProviderError):
                await provider.complete_structured([], {"type": "object"}, profile, timeout_s=5)
        assert requests == ["/v1/chat/completions"]
        assert key.tokens_used == 0  # HTTP quota denial is not token expenditure=limit.
        observed = await service.snapshot(profile, facts, timeout_s=3)
        assert observed.tokens_used == 0 and not observed.usage_known and observed.requests_today == 1
    finally:
        await provider.aclose()


async def test_public_compatibility_and_operator_cli_reconcile_use_same_ledger(accounting_case):
    from dataclasses import replace

    from app.api import settings
    from app.db.session import psycopg_dsn
    from app.llm import accounting_cli, credentials

    service, template, original_facts = accounting_case
    created = await settings.post_llm_keys(
        settings.LlmKeyBody(
            provider="gigachat",
            label="synthetic-cli",
            key=original_facts.secret,
            endpoint_url=original_facts.endpoint,
            tokens_limit=20,
            rpd_limit=2,
        )
    )
    key_id = created["id"]
    assert created["tokens_used"] == 0 and created["observed_tokens_floor"] == 0
    assert not created["usage_known"] and created["tokens_remaining"] is None
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        await conn.execute("update llm_api_keys set tokens_used=17 where id=%s", (key_id,))
        profile_id = (
            await (
                await conn.execute(
                    "insert into llm_profiles(code,provider,model,role,base_url,api_key_id,rpd_limit) values(%s,'gigachat','synthetic','main',%s,%s,2) returning id",
                    (template.code, original_facts.endpoint, key_id),
                )
            ).fetchone()
        )[0]
    before = next(item for item in await settings.get_llm_keys() if item["id"] == key_id)
    assert before["tokens_used"] == 17  # Original legacy migration compatibility assertion remains valid.
    assert before["observed_tokens_floor"] == 0 and not before["usage_known"]
    assert before["usage_source"] == "legacy_unverified" and before["tokens_remaining"] is None
    args = accounting_cli.parser().parse_args(
        [
            "reconcile",
            "--profile-id",
            str(profile_id),
            "--key-id",
            str(key_id),
            "--reconciliation-id",
            str(uuid.uuid4()),
            "--as-of",
            (await now()).isoformat(),
            "--tokens-used",
            "0",
            "--requests-today",
            "0",
            "--profile-requests-today",
            "0",
            "--confirm",
            "--reviewed-unknown-origin",
        ]
    )
    receipt = await accounting_cli.execute(args)
    assert not receipt["idempotent"]
    assert (await accounting_cli.execute(args))["idempotent"]
    profile = replace(template, id=profile_id, api_key_id=key_id, base_url=original_facts.endpoint)
    facts = replace(original_facts, db_id=key_id)
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit()
        await ticket.observe(2, 3, final=True)
    after = next(item for item in await settings.get_llm_keys() if item["id"] == key_id)
    assert after["tokens_used"] == after["observed_tokens_floor"] == 5 and after["usage_known"]
    assert after["tokens_remaining"] == 15 and after["requests_today"] == 1 and after["requests_remaining"] == 1
    assert set(after) == set(credentials.PUBLIC_FIELDS)
    assert not {"uid", "verifier", "credential_uid", "quota_uid", "_secret"} & after.keys()
    assert facts.secret not in str(after) + str(receipt)
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        mirrors = await (
            await conn.execute("select tokens_used,requests_today from llm_api_keys where id=%s", (key_id,))
        ).fetchone()
        assert mirrors == (5, 1)


async def test_existing_metadata_refresh_serializes_rpd_and_recomputes_public_remaining(accounting_case, monkeypatch):
    import asyncio
    from dataclasses import replace

    from app.api import settings
    from app.db.session import psycopg_dsn
    from app.llm import credentials

    service, original, source = accounting_case
    profile = replace(original, provider="openai_compatible")
    facts = replace(source, provider="openai_compatible")
    created = await settings.post_llm_keys(
        settings.LlmKeyBody(
            provider="openai_compatible",
            label="synthetic-metadata",
            key=facts.secret,
            endpoint_url=facts.endpoint,
            tokens_limit=20,
            rpd_limit=2,
        )
    )
    profile = replace(profile, api_key_id=created["id"], base_url=facts.endpoint)
    await confirm((service, profile, facts))
    ready, proceed = asyncio.Event(), asyncio.Event()
    load_keys = settings.load_keys
    backend_pids = []

    async def track(conn, **kwargs):
        backend_pids.append(conn.info.backend_pid)
        return await load_keys(conn, **kwargs)

    async def metadata(items):
        next(item for item in items if item["id"] == created["id"])["rpd_limit"] = 3
        ready.set()
        await proceed.wait()
        return True  # Synthetic result; no additional GET/key or any HTTP.

    monkeypatch.setattr(settings, "load_keys", track)
    monkeypatch.setattr(settings, "_refresh_openai_balances", metadata)
    task = asyncio.create_task(settings.get_llm_keys())
    await ready.wait()
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as blocker:
        async with blocker.transaction():
            await blocker.execute("select pg_advisory_xact_lock(%s)", (credentials.LOCK,))
            proceed.set()
            async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as observer:
                async with asyncio.timeout(3):
                    while True:
                        waiting = (
                            await (
                                await observer.execute(
                                    "select exists(select 1 from pg_locks where pid=%s and locktype='advisory' and not granted)",
                                    (backend_pids[0],),
                                )
                            ).fetchone()
                        )[0]
                        if waiting:
                            break
                        await asyncio.sleep(0)
            assert not task.done()
        public = next(item for item in await task if item["id"] == created["id"])
    assert public["rpd_limit"] == public["requests_remaining"] == 3
    assert public["requests_today"] == 0 and public["requests_known"]


@pytest.mark.parametrize("provider_name", ["gigachat", "openai_compatible"])
async def test_stream_deadline_never_cancels_consumer_between_pulls(accounting_case, provider_name):
    import asyncio
    from dataclasses import replace

    import httpx

    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool
    from app.llm.openai_compat import OpenAICompatProvider

    service, original, source = accounting_case
    profile, facts = replace(original, provider=provider_name), replace(source, provider=provider_name)
    await confirm((service, profile, facts))
    calls = []

    def fake(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"prefix"}}]}\n\ndata: [DONE]\n\n',
            headers={"Content-Type": "text/event-stream"},
        )

    if provider_name == "gigachat":
        key = ApiKey(
            "synthetic", facts.secret, tokens_limit=20, access_token="synthetic-access", token_expires_at=9999999999
        )
        provider = GigaChatProvider(
            KeyPool([key]),
            oauth_url="https://synthetic.invalid/oauth",
            base_url=facts.endpoint,
            transport=httpx.MockTransport(fake),
        )
    else:
        provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(fake))
    stream = provider.stream([], profile, timeout_s=2)
    try:
        assert await anext(stream) == "prefix"
        # This is consumer work OUTSIDE the provider generator. Its deadline may
        # reject the next pull, but must never asynchronously cancel this task.
        await asyncio.sleep(2.1)
        with pytest.raises(ProviderError) as expired:
            await anext(stream)
        assert expired.value.kind == "timeout" and expired.value.usage is None
        assert calls == ["/v1/chat/completions"]
    finally:
        await stream.aclose()
        await provider.aclose()
    observed = await service.snapshot(profile, facts, timeout_s=3)
    assert observed.requests_today == 1 and not observed.usage_known


@pytest.mark.parametrize("provider_name", ["gigachat", "openai_compatible"])
async def test_stream_blocked_io_has_absolute_deadline_and_preserves_known_floor(accounting_case, provider_name):
    import asyncio
    from dataclasses import replace

    import httpx

    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool
    from app.llm.openai_compat import OpenAICompatProvider

    service, original, source = accounting_case
    profile, facts = replace(original, provider=provider_name), replace(source, provider=provider_name)
    await confirm((service, profile, facts))
    calls = []

    class Blocked(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            try:
                yield b'data: {"choices":[{"delta":{"content":"prefix"}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
                await asyncio.Event().wait()
            finally:
                self.closed = True

        async def aclose(self):
            self.closed = True

    body = Blocked()

    def fake(request):
        calls.append(request.url.path)
        return httpx.Response(200, stream=body, headers={"Content-Type": "text/event-stream"})

    if provider_name == "gigachat":
        key = ApiKey(
            "synthetic", facts.secret, tokens_limit=20, access_token="synthetic-access", token_expires_at=9999999999
        )
        provider = GigaChatProvider(
            KeyPool([key]),
            oauth_url="https://synthetic.invalid/oauth",
            base_url=facts.endpoint,
            transport=httpx.MockTransport(fake),
        )
    else:
        provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(fake))
    stream = provider.stream([], profile, timeout_s=2)
    try:
        assert await anext(stream) == "prefix"
        with pytest.raises(ProviderError) as expired:
            await asyncio.wait_for(anext(stream), 4)
        assert expired.value.kind == "timeout"
        assert expired.value.usage.total_tokens == 2  # Lower observation, not a completeness claim.
        assert body.closed and calls == ["/v1/chat/completions"]
    finally:
        await stream.aclose()
        await provider.aclose()
    observed = await service.snapshot(profile, facts, timeout_s=3)
    assert observed.tokens_used == 2 and not observed.usage_known and observed.tokens_remaining is None
    assert observed.requests_today == 1


@pytest.mark.parametrize("provider_name", ["gigachat", "openai_compatible"])
async def test_actual_chain_deadline_keeps_single_source_and_durable_partial_usage(accounting_case, provider_name):
    import asyncio
    from dataclasses import replace

    import httpx

    from app.llm.failover import ProviderChain
    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import ApiKey, KeyPool
    from app.llm.openai_compat import OpenAICompatProvider

    service, original, source = accounting_case
    profile, facts = replace(original, provider=provider_name), replace(source, provider=provider_name)
    await confirm((service, profile, facts))
    calls = []

    class Blocked(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"prefix"}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
            await asyncio.Event().wait()

    def fake(request):
        calls.append(request.url.path)
        return httpx.Response(200, stream=Blocked(), headers={"Content-Type": "text/event-stream"})

    class ForbiddenMock:
        name = "mock"
        called = False

        async def stream(self, *args, **kwargs):
            self.called = True
            yield "fallback-must-not-be-mixed"

    fallback = ForbiddenMock()
    if provider_name == "gigachat":
        key = ApiKey(
            "synthetic", facts.secret, tokens_limit=20, access_token="synthetic-access", token_expires_at=9999999999
        )
        provider = GigaChatProvider(
            KeyPool([key]),
            oauth_url="https://synthetic.invalid/oauth",
            base_url=facts.endpoint,
            transport=httpx.MockTransport(fake),
        )
    else:
        provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(fake))
    stream = ProviderChain([provider, fallback], timeouts={"default": 2}).stream([], profile)
    try:
        assert await anext(stream) == "prefix"
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), 4)
        assert not fallback.called and calls == ["/v1/chat/completions"]
    finally:
        await stream.aclose()
        await provider.aclose()
    observed = await service.snapshot(profile, facts, timeout_s=3)
    assert observed.tokens_used == 2 and observed.requests_today == 1 and not observed.usage_known


@pytest.mark.parametrize("slot", ["gigachat1", "gigachat2", "openrouter", "local"])
async def test_operator_cli_env_sources_are_explicit_reconciled_and_show_profile_day(migrated_db, monkeypatch, slot):
    import json

    from app.db.session import psycopg_dsn
    from app.llm import accounting_cli

    suffix = uuid.uuid4().hex
    provider = "gigachat" if slot.startswith("gigachat") else "openai_compatible"
    endpoint = f"https://synthetic-{slot}.invalid/v1/{suffix}"
    secret = f"synthetic-cli-{slot}-{suffix}"
    field = {
        "gigachat1": "GIGACHAT_AUTH_KEY_1",
        "gigachat2": "GIGACHAT_AUTH_KEY_2",
        "openrouter": "OPENROUTER_API_KEY",
        "local": "LOCAL_LLM_API_KEY",
    }[slot]
    url_field = (
        "GIGACHAT_BASE_URL"
        if provider == "gigachat"
        else ("LOCAL_LLM_BASE_URL" if slot == "local" else "OPENROUTER_BASE_URL")
    )
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv(field, secret)
    monkeypatch.setenv(url_field, endpoint)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        pid = (
            await (
                await conn.execute(
                    "insert into llm_profiles(code,provider,model,role,base_url,rpd_limit) values(%s,%s,'synthetic','main',%s,2) returning id",
                    (f"cli-{suffix}", provider, endpoint),
                )
            ).fetchone()
        )[0]
    args = accounting_cli.parser().parse_args(["status", "--profile-id", str(pid), "--env-slot", slot])
    before = await accounting_cli.execute(args)
    assert not before["admission_allowed"] and not before["usage_known"] and not before["profile_requests_known"]
    args = accounting_cli.parser().parse_args(
        [
            "reconcile",
            "--profile-id",
            str(pid),
            "--env-slot",
            slot,
            "--reconciliation-id",
            str(uuid.uuid4()),
            "--as-of",
            (await now()).isoformat(),
            "--tokens-used",
            "0",
            "--requests-today",
            "0",
            "--profile-requests-today",
            "0",
            "--confirm",
            "--reviewed-unknown-origin",
        ]
    )
    receipt = await accounting_cli.execute(args)
    after = await accounting_cli.execute(
        accounting_cli.parser().parse_args(["status", "--profile-id", str(pid), "--env-slot", slot])
    )
    assert after["admission_allowed"] and after["usage_known"] and after["profile_requests_known"]
    assert after["profile_requests_today"] == 0 and after["profile_requests_remaining"] == 2
    rendered = json.dumps([before, receipt, after], default=str)
    assert secret not in rendered and not any(name in rendered for name in ("verifier", "quota_uid", "credential_uid"))
    get_settings.cache_clear()


async def test_operator_cli_keyless_local_and_wrong_env_binding_fail_closed(migrated_db, monkeypatch):
    from app.db.session import psycopg_dsn
    from app.llm import accounting_cli

    suffix = uuid.uuid4().hex
    base = f"http://127.0.0.1:4545/v1/{suffix}"
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", base)
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GIGACHAT_AUTH_KEY_2", raising=False)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        pid = (
            await (
                await conn.execute(
                    "insert into llm_profiles(code,provider,model,role,base_url,rpd_limit) values(%s,'openai_compatible','synthetic','main',%s,2) returning id",
                    (f"cli-local-{suffix}", base),
                )
            ).fetchone()
        )[0]
        args = accounting_cli.parser().parse_args(["status", "--profile-id", str(pid), "--env-slot", "local"])
        profile, facts = await accounting_cli.selection(args)
        assert facts.secret is None and facts.endpoint == base
        for wrong in ("gigachat2", "openrouter"):
            with pytest.raises(ProviderError) as denied:
                await accounting_cli.selection(
                    accounting_cli.parser().parse_args(["status", "--profile-id", str(pid), "--env-slot", wrong])
                )
            assert denied.value.kind == "auth"
        await conn.execute("update llm_profiles set base_url=%s where id=%s", (base + "/other", pid))
        with pytest.raises(ProviderError, match="local env source"):
            await accounting_cli.selection(args)
    get_settings.cache_clear()


async def test_private_migration_normalizes_pre_release_default_without_rewinding_history(accounting_case):
    from pathlib import Path

    from app.db.session import psycopg_dsn

    service, profile, facts = accounting_case
    await confirm(accounting_case)
    async with service.key_scope(profile, facts, timeout_s=3) as scope:
        ticket = await scope.admit()
        await ticket.observe(2, 3, final=True)
    sql = (Path(__file__).resolve().parents[3] / "contracts/db/migrations/0016_llm_accounting.sql").read_text()
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        await conn.execute("alter table llm_runtime.wire_attempts alter column profile_code set default ''")
        for _ in range(2):
            await conn.execute(sql)
        actual = (
            await (
                await conn.execute(
                    "select column_default from information_schema.columns where table_schema='llm_runtime' and table_name='wire_attempts' and column_name='profile_code'"
                )
            ).fetchone()
        )[0]
        assert actual is None
    observed = await service.snapshot(profile, facts, timeout_s=3)
    assert observed.tokens_used == 5 and observed.requests_today == 1 and observed.usage_known


async def test_paid_sdk_stream_candidate_uses_endpoint_classification_before_any_http(accounting_case):
    from dataclasses import replace

    import httpx

    from app.llm.openai_compat import OpenAICompatProvider

    _, original, source = accounting_case
    profile = replace(original, provider="gigachat", model="paid-model", rpd_limit=None)
    # Legacy stream-chain may try an SDK candidate with the requested Giga tag.
    # The actual paid endpoint remains budgeted; a display tag is not an exemption.
    calls = []

    def fake(request):
        calls.append(request.url.path)
        pytest.fail("unknown paid origin must be rejected before metadata or inference HTTP")

    provider = OpenAICompatProvider(source.secret, "https://openrouter.ai/api/v1", transport=httpx.MockTransport(fake))
    try:
        with pytest.raises(ProviderError) as denied:
            await anext(provider.stream([], profile, timeout_s=3))
        assert denied.value.kind == "quota" and calls == []
    finally:
        await provider.aclose()


async def test_env_provider_tier_is_not_reported_as_configured_key_cap(accounting_case):
    from dataclasses import replace

    import httpx

    from app.api.settings import public_openrouter_env_key
    from app.db.session import psycopg_dsn
    from app.llm.accounting import attach_env_observation
    from app.llm.openai_compat import OpenAICompatProvider

    service, original, source = accounting_case
    profile = replace(original, provider="openai_compatible", model="synthetic:free")
    facts = KeyFacts("openai_compatible", source.secret, source.endpoint)
    await confirm((service, profile, facts))
    calls = []

    def fake(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": profile.model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )

    provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(fake))
    try:
        for count in (1, 2):
            await provider.complete_structured([], {"type": "object"}, profile, timeout_s=3)
            card = public_openrouter_env_key(
                [], {"rpd_limit": 1, "balance_usd": 17}, key_hint="…synthetic", last_error=None
            )[0]
            async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
                public = await attach_env_observation(conn, card, facts)
            assert public["rpd_limit"] is None and public["requests_remaining"] is None
            assert public["requests_today"] == count and public["requests_known"]
            assert public["balance_usd"] == 17  # Existing informational balance retained.
            actual = await service.snapshot(profile, facts, timeout_s=3)
            assert actual.profile_requests_remaining == 2 - count
        with pytest.raises(ProviderError) as exhausted:
            await provider.complete_structured([], {"type": "object"}, profile, timeout_s=3)
        assert exhausted.value.kind == "rate_limit" and calls == ["/v1/chat/completions"] * 2
    finally:
        await provider.aclose()


async def test_nemotron_json_mode_unknown_still_blocks_second_http(accounting_case):
    from dataclasses import replace

    import httpx

    from app.contracts.registry import deref
    from app.llm.openai_compat import OpenAICompatProvider

    service, original, original_facts = accounting_case
    profile = replace(original, provider="openai_compatible", model="nvidia/nemotron-3-ultra-550b-a55b:free")
    facts = replace(original_facts, provider="openai_compatible", endpoint="https://openrouter.ai/api/v1")
    await confirm((service, profile, facts))
    seen = []

    def handler(request):
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"error": {"code": 400, "message": "synthetic upstream failure"}})

    provider = OpenAICompatProvider(facts.secret, facts.endpoint, transport=httpx.MockTransport(handler))
    try:
        for expected in ("bad_output", "quota"):
            with pytest.raises(ProviderError) as rejected:
                await provider.complete_structured([], deref("agent/normalization"), profile, timeout_s=5)
            assert rejected.value.kind == expected
        assert len(seen) == 1 and seen[0]["response_format"] == {"type": "json_object"}
        observed = await service.snapshot(profile, facts, timeout_s=3)
        assert not observed.usage_known and observed.requests_today == 1 and observed.tokens_used == 0
        async with await psycopg.AsyncConnection.connect(
            get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1), row_factory=dict_row
        ) as conn:
            row = await (await conn.execute(
                "select state,count(*) as n from llm_runtime.wire_attempts where profile_code=%s group by state",
                (profile.code,),
            )).fetchone()
            assert row == {"state": "unknown", "n": 1}
    finally:
        await provider.aclose()
