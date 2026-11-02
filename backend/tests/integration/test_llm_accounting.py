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
