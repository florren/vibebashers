"""T-051: только synthetic credentials, PGP migration и per-AR configuration."""

from __future__ import annotations

import json

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.errors import Problem
from app.llm import credentials
from app.llm.base import LLMProfile
from app.llm.runtime_provider import BoundPlaceholder, selected_provider
from app.llm.secrets import encrypt

pytestmark = pytest.mark.integration


async def connect(url):
    return await psycopg.AsyncConnection.connect(url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True)


def preupgrade_legacy_row(conn, items):
    # Только synthetic fixture: имитируем row, которая существовала ДО0013.
    # Отключается один именованный trigger. Savepoint сохраняет возможность
    # включить его в finally; при потере соединения transactional DDL откатится.
    with conn.transaction():
        conn.execute("alter table settings disable trigger settings_legacy_llm_key_writes")
        try:
            with conn.transaction():
                conn.execute(
                    "insert into settings(key,value) values('llm_keys',%s) on conflict(key) do update set value=excluded.value",
                    (Jsonb(items),),
                )
        finally:
            conn.execute("alter table settings enable trigger settings_legacy_llm_key_writes")


async def test_legacy_cutover_is_pgp_atomic_idempotent_and_public(seeded, conn):
    secret = "synthetic-legacy-credential"
    legacy = [
        {
            "id": 23,
            "provider": "gigachat",
            "label": "synthetic",
            "key_enc": encrypt(secret, get_settings().app_secret),
            "tokens_used": 17,
        }
    ]
    preupgrade_legacy_row(conn, legacy)
    async with await connect(seeded) as ac:
        first = await credentials.list_keys(ac)
        encrypted = conn.execute("select encrypted_key from llm_api_keys where id=23").fetchone()[0]
        assert (
            conn.execute(
                "select pgp_sym_decrypt(encrypted_key,%s) from llm_api_keys where id=23", (get_settings().app_secret,)
            ).fetchone()[0]
            == secret
        )
        assert conn.execute("select value from settings where key='llm_keys'").fetchone() is None
        assert first == await credentials.list_keys(ac)
        assert conn.execute("select encrypted_key from llm_api_keys where id=23").fetchone()[0] == encrypted
        public = next(item for item in first if item["id"] == 23)
        assert public["tokens_used"] == 17
        assert set(public) == set(credentials.PUBLIC_FIELDS)
        assert secret not in json.dumps(public, default=str)
        assert "key_enc" not in public and "credential_uid" not in public and "encrypted_key" not in public
        created = conn.execute(
            "insert into llm_api_keys(provider,label,encrypted_key) values('gigachat','next',pgp_sym_encrypt('synthetic-next',%s)) returning id",
            (get_settings().app_secret,),
        ).fetchone()[0]
        assert created > 23


async def test_legacy_collision_rolls_back_entire_import(seeded, conn):
    conn.execute(
        "insert into llm_api_keys(id,provider,label,encrypted_key) overriding system value values(9,'gigachat','canonical',pgp_sym_encrypt('synthetic-existing',%s))",
        (get_settings().app_secret,),
    )
    items = [
        {
            "id": kid,
            "provider": "gigachat",
            "label": "legacy",
            "key_enc": encrypt("synthetic-legacy", get_settings().app_secret),
        }
        for kid in (8, 9)
    ]
    preupgrade_legacy_row(conn, items)
    async with await connect(seeded) as ac:
        with pytest.raises(Problem, match="изменения отменены"):
            await credentials.migrate_legacy(ac)
    assert conn.execute("select id from llm_api_keys where id=8").fetchone() is None
    assert conn.execute("select value from settings where key='llm_keys'").fetchone()[0] == items


async def test_bound_wire_uses_saved_key_exact_endpoint_and_closes(seeded, conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    base = "https://synthetic.invalid/v1"
    secret = "synthetic-bound-key"
    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url) values('openai_compatible','bound',pgp_sym_encrypt(%s,%s),%s) returning id",
        (secret, get_settings().app_secret, base),
    ).fetchone()[0]
    profile = LLMProfile(
        code="bound", provider="openai_compatible", model="synthetic:free", base_url=base, api_key_id=kid
    )
    seen = []

    def handle(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": "synthetic:free",
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop", "index": 0}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    async with selected_provider(
        BoundPlaceholder("openai_compatible"), profile, transport=httpx.MockTransport(handle)
    ) as provider:
        result, usage, _ = await provider.complete_structured(
            [{"role": "user", "content": "fixed synthetic"}],
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            profile,
            timeout_s=2,
        )
        assert result == {"ok": True} and usage.total_tokens == 4
    assert seen == [(base + "/chat/completions", "Bearer " + secret)]
    assert provider._client.is_closed
    conn.execute("update llm_api_keys set is_active=false where id=%s", (kid,))
    with pytest.raises(Problem, match="Выбранный API-ключ"):
        async with selected_provider(
            BoundPlaceholder("openai_compatible"), profile, transport=httpx.MockTransport(handle)
        ):
            pytest.fail("revoked key must not enter provider")
    assert len(seen) == 1
    get_settings.cache_clear()


async def test_new_ar_hot_applies_roles_while_existing_ar_and_initial_main_override_stay_pinned(
    seeded, conn, monkeypatch
):
    from types import SimpleNamespace

    from app.llm.failover import ProviderChain
    from app.llm.run_profiles import resolve
    from app.sim import runs

    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    ids = {}
    for role in ("main", "fast", "twin"):
        ids[role] = conn.execute(
            "insert into llm_profiles(code,provider,model,role) values(%s,'gigachat',%s,%s) returning id",
            ("hot-" + role, "A-" + role, role),
        ).fetchone()[0]
    conn.execute(
        "insert into settings(key,value) values('setup_payload',%s) on conflict(key) do update set value=excluded.value",
        (Jsonb({"llm": {role + "_profile_id": pid for role, pid in ids.items()}}),),
    )
    original = ProviderChain([SimpleNamespace(name="gigachat")])
    default = LLMProfile(code="global", provider="gigachat", model="global")
    now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    async with await connect(seeded) as ac:
        rid = await runs.create_run(ac, kind="free", label="hot apply", seed=7, sim_time=now)
        explicit = await runs.create_run(
            ac, kind="free", label="initial main override", seed=7, sim_time=now, llm_profile_id=ids["main"]
        )
        first, _ = await resolve(ac, rid, original, default, new=True)
        ar = conn.execute(
            "insert into agent_runs(kind,sim_run_id,llm_profile_id,prompt_version,graph_version,started_sim,llm_profiles_snapshot) values('agent',%s,%s,'synthetic','synthetic',%s,%s) returning id",
            (rid, ids["main"], now, Jsonb(first.role_snapshot)),
        ).fetchone()[0]
        conn.execute("update llm_profiles set model='B-'||role where id=any(%s)", (list(ids.values()),))
        second, _ = await resolve(ac, rid, original, default, new=True)
        resumed, _ = await resolve(
            ac,
            rid,
            original,
            LLMProfile(code="mutable-current-main", provider="mock", model="current-mock"),
            agent_run_id=ar,
        )
        overridden, _ = await resolve(ac, explicit, original, default, new=True)
        conn.execute("update llm_profiles set provider='mock' where id=%s", (ids["main"],))
        mixed, _ = await resolve(ac, rid, original, default, new=True)
    assert {r: p.model for r, p in first.role_profiles.items()} == {r: "A-" + r for r in ids}
    assert {r: p.model for r, p in second.role_profiles.items()} == {r: "B-" + r for r in ids}
    assert {r: p.model for r, p in resumed.role_profiles.items()} == {r: "A-" + r for r in ids}
    assert {r: p.model for r, p in overridden.role_profiles.items()} == {
        "main": "A-main",
        "fast": "B-fast",
        "twin": "B-twin",
    }
    assert {profile.provider for profile in resumed.role_profiles.values()} == {"gigachat"}
    assert {role: profile.provider for role, profile in mixed.role_profiles.items()} == {
        "main": "mock",
        "fast": "gigachat",
        "twin": "gigachat",
    }
    assert original.role_profiles == {} and original.role_snapshot is None
    assert first.role_snapshot["provenance"] == "current_roles"
    assert overridden.role_snapshot["provenance"] == "current_roles_with_initial_main_override"
    get_settings.cache_clear()


def test_key_api_has_one_pgp_source_private_identity_and_explicit_unbind(seeded, conn, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    secret = "synthetic-api-credential"
    base = "https://synthetic-a.invalid/v1"
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/settings/llm-keys",
            json={"provider": "openai_compatible", "label": "synthetic-key", "key": secret, "endpoint_url": base},
        )
        assert response.status_code == 201, response.text
        kid = response.json()["id"]
        encrypted, uid = conn.execute(
            "select encrypted_key,credential_uid from llm_api_keys where id=%s", (kid,)
        ).fetchone()
        assert secret.encode() not in encrypted
        body = {
            "code": "synthetic-bound-profile",
            "provider": "openai_compatible",
            "model": "synthetic:free",
            "base_url": base,
            "api_key_id": kid,
            "role": "bench_only",
        }
        assert client.post("/api/settings/llm-profiles", json=body).status_code == 201
        profile = next(row for row in client.get("/api/settings/llm-profiles").json() if row["code"] == body["code"])
        assert profile["api_key_id"] == kid
        old_client_body = {key: value for key, value in body.items() if key != "api_key_id"}
        assert client.patch(f"/api/settings/llm-profiles/{profile['id']}", json=old_client_body).status_code == 200
        assert conn.execute("select api_key_id from llm_profiles where id=%s", (profile["id"],)).fetchone()[0] == kid
        assert client.delete(f"/api/settings/llm-keys/{kid}").status_code == 409
        assert (
            client.patch(
                f"/api/settings/llm-profiles/{profile['id']}",
                json={**body, "base_url": "https://synthetic-b.invalid/v1"},
            ).status_code
            == 409
        )
        assert conn.execute("select base_url from llm_profiles where id=%s", (profile["id"],)).fetchone()[0] == base
        for path in ("/api/settings", "/api/settings/export", "/api/setup", "/api/settings/llm-keys"):
            public = client.get(path)
            assert public.status_code == 200, public.text
            assert secret not in public.text and str(uid) not in public.text
            assert encrypted.hex() not in public.text
            assert "encrypted_key" not in public.text and "credential_uid" not in public.text
        assert client.get("/api/engine/db/tables/llm_api_keys/rows?run_id=all").status_code == 403
        assert (
            client.patch(f"/api/settings/llm-profiles/{profile['id']}", json={**body, "api_key_id": None}).status_code
            == 200
        )
        assert client.delete(f"/api/settings/llm-keys/{kid}").status_code == 204
        alias = client.post(
            "/api/settings/llm-keys",
            json={"provider": "openai_compatible", "label": "synthetic-alias", "key": secret, "endpoint_url": base},
        )
        assert alias.status_code == 201
        alias_id = alias.json()["id"]
        assert alias_id > kid
        assert conn.execute("select credential_uid from llm_api_keys where id=%s", (alias_id,)).fetchone()[0] == uid
        # Исторический bench extra pointer читается явно, но новые writes только через API field.
        conn.execute("update llm_profiles set extra=%s where id=%s", (Jsonb({"api_key_id": alias_id}), profile["id"]))
        projected = next(row for row in client.get("/api/settings/llm-profiles").json() if row["id"] == profile["id"])
        assert projected["api_key_id"] == alias_id and projected["extra"] == {}
        assert client.delete(f"/api/settings/llm-keys/{alias_id}").status_code == 409
        assert client.patch(f"/api/settings/llm-profiles/{profile['id']}", json=projected).status_code == 200
        assert conn.execute("select api_key_id,extra from llm_profiles where id=%s", (profile["id"],)).fetchone() == (
            alias_id,
            {},
        )
        assert (
            client.post(
                "/api/settings/llm-profiles", json={**body, "code": "rejected-extra", "extra": {"api_key_id": alias_id}}
            ).status_code
            == 422
        )
    get_settings.cache_clear()


@pytest.mark.parametrize("invalid", ["missing", "inactive", "provider", "endpoint"])
async def test_invalid_explicit_binding_refuses_before_any_http(seeded, conn, monkeypatch, invalid):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    base = "https://synthetic.invalid/v1"
    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url) values('openai_compatible','synthetic',pgp_sym_encrypt('synthetic-only',%s),%s) returning id",
        (get_settings().app_secret, base),
    ).fetchone()[0]
    if invalid == "missing":
        kid += 1000000
    elif invalid == "inactive":
        conn.execute("update llm_api_keys set is_active=false where id=%s", (kid,))
    elif invalid == "provider":
        conn.execute("update llm_api_keys set provider='gigachat' where id=%s", (kid,))
    else:
        conn.execute("update llm_api_keys set endpoint_url='https://other-synthetic.invalid/v1' where id=%s", (kid,))
    profile = LLMProfile(
        code="refused", provider="openai_compatible", model="synthetic:free", base_url=base, api_key_id=kid
    )

    def forbidden(request):
        pytest.fail("invalid binding must not perform HTTP or fallback env")

    with pytest.raises(Problem):
        async with selected_provider(
            BoundPlaceholder("openai_compatible"), profile, transport=httpx.MockTransport(forbidden)
        ):
            pytest.fail("invalid binding must not create a callable provider")
    get_settings.cache_clear()


@pytest.mark.parametrize("role", ["main", "fast", "twin"])
def test_baseline_none_profile_preflight_rejects_each_bad_selected_role_before_restore(seeded, conn, monkeypatch, role):
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    from app.api import sim as sim_api
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url,is_active) values('gigachat','synthetic',pgp_sym_encrypt('synthetic-only',%s),'https://synthetic.invalid/v1',false) returning id",
        (get_settings().app_secret,),
    ).fetchone()[0]
    pid = conn.execute(
        "insert into llm_profiles(code,provider,model,role,api_key_id) values(%s,'gigachat','synthetic',%s,%s) returning id",
        ("invalid-" + role, role, kid),
    ).fetchone()[0]
    conn.execute(
        "insert into settings(key,value) values('setup_payload',%s) on conflict(key) do update set value=excluded.value",
        (Jsonb({"llm": {role + "_profile_id": pid}}),),
    )
    restore = AsyncMock()
    monkeypatch.setattr(sim_api, "_restore_baseline", restore)
    with TestClient(create_app()) as client:
        response = client.post("/api/sim/runs", json={"kind": "free", "reset_mode": "baseline", "llm_profile_id": None})
    assert response.status_code == 409
    assert "Выбранный API-ключ" in response.text
    restore.assert_not_awaited()
    get_settings.cache_clear()


async def test_bound_giga_closing_clients_does_not_reset_key_usage_or_health(seeded, conn, monkeypatch):
    from app.llm.base import ProviderError

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    base = "https://synthetic-giga.invalid/v1"
    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url,scope,tokens_limit) values('gigachat','synthetic',pgp_sym_encrypt('synthetic-only',%s),%s,%s,4) returning id",
        (get_settings().app_secret, base, get_settings().gigachat_scope),
    ).fetchone()[0]
    profile = LLMProfile(code="bounded", provider="gigachat", model="synthetic", base_url=base, api_key_id=kid)
    seen = []

    def handle(request):
        seen.append(str(request.url))
        if request.url.path.endswith("oauth"):
            return httpx.Response(200, json={"access_token": "synthetic-access", "expires_at": 4102444800000})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    transport = httpx.MockTransport(handle)
    async with selected_provider(BoundPlaceholder("gigachat"), profile, transport=transport) as first:
        obj, usage, _ = await first.complete_structured(
            [{"role": "user", "content": "fixed synthetic"}],
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            profile,
            timeout_s=2,
        )
        assert obj == {"ok": True} and usage.total_tokens == 4
        key = first.pool.keys[0]
    assert first._client.is_closed and key.tokens_used == 4
    before = len(seen)
    async with selected_provider(BoundPlaceholder("gigachat"), profile, transport=transport) as second:
        assert second.pool.keys[0] is key
        assert second._token_locks is first._token_locks
        with pytest.raises(ProviderError) as refused:
            await second.complete_structured(
                [{"role": "user", "content": "fixed synthetic"}], {"type": "object"}, profile, timeout_s=2
            )
        assert refused.value.kind == "quota"
    assert second._client.is_closed and len(seen) == before == 2
    get_settings.cache_clear()


def test_old_app_legacy_writes_fail_closed_after_upgrade(seeded, conn):
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        conn.execute(
            "insert into settings(key,value) values('llm_keys',%s)", (Jsonb([{"key_enc": "synthetic-cipher"}]),)
        )
    assert "synthetic-cipher" not in str(refused.value)
    assert "Legacy LLM key writes are disabled" in str(refused.value)
    assert conn.execute("select value from settings where key='llm_keys'").fetchone() is None


@pytest.mark.parametrize("stage", ["oauth_error", "chat_error", "model_200"])
def test_setup_check_never_returns_upstream_credential_echo(seeded, monkeypatch, stage):
    import time

    from fastapi.testclient import TestClient

    from app.llm import gigachat
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    secret = "synthetic-setup-credential"
    actual = gigachat.GigaChatProvider
    clients = []

    def handle(request):
        if request.url.path.endswith("oauth"):
            if stage == "oauth_error":
                return httpx.Response(401, text="Authorization: Basic " + secret)
            return httpx.Response(
                200, json={"access_token": "synthetic-access-token", "expires_at": (time.time() + 3600) * 1000}
            )
        if stage == "chat_error":
            return httpx.Response(403, text="Authorization: Basic " + secret)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"ok": True, "model": secret})}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    def factory(*args, **kwargs):
        instance = actual(*args, **kwargs, transport=httpx.MockTransport(handle))
        clients.append(instance)
        return instance

    monkeypatch.setattr(gigachat, "GigaChatProvider", factory)
    with TestClient(create_app()) as client:
        result = client.post(
            "/api/setup/test-llm",
            json={
                "provider": "gigachat",
                "model": "synthetic-model",
                "api_key": secret,
                "base_url": "https://synthetic.invalid/v1",
            },
        )
    assert result.status_code == 200 and result.json()["ok"] is False
    assert secret not in result.text
    assert clients and all(instance._client.is_closed for instance in clients)
    get_settings.cache_clear()


async def test_metadata_binding_validation_does_not_decrypt_or_cut_over(seeded, conn, monkeypatch):
    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url,scope) values('gigachat','synthetic',pgp_sym_encrypt('synthetic-only',%s),'https://synthetic.invalid/v1',%s) returning id",
        (get_settings().app_secret, get_settings().gigachat_scope),
    ).fetchone()[0]
    preupgrade_legacy_row(
        conn, [{"id": kid + 1, "provider": "gigachat", "label": "legacy", "key_enc": "synthetic-not-decoded"}]
    )

    def forbidden(*args):
        pytest.fail("metadata preflight must not decrypt legacy data")

    monkeypatch.setattr(credentials.legacy, "decrypt", forbidden)
    async with await connect(seeded) as ac:
        item = await credentials.validate_binding(
            ac,
            LLMProfile(
                code="metadata",
                provider="gigachat",
                model="synthetic",
                base_url="https://synthetic.invalid/v1",
                api_key_id=kid,
            ),
        )
    assert item["id"] == kid and "_secret" not in item and "_credential_uid" not in item
    assert conn.execute("select value from settings where key='llm_keys'").fetchone() is not None


async def test_config_fingerprint_tracks_new_binding_metadata_but_not_usage(seeded, conn):
    from app.sim import baseline_llm

    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url,scope,tokens_limit,rpd_limit) values('gigachat','synthetic',pgp_sym_encrypt('synthetic-only',%s),'https://synthetic.invalid/v1',%s,1000,20) returning id",
        (get_settings().app_secret, get_settings().gigachat_scope),
    ).fetchone()[0]
    async with await connect(seeded) as ac:
        original = await baseline_llm.read(ac)
        conn.execute(
            "update llm_api_keys set tokens_used=17,requests_today=3,requests_day=current_date,balance_usd=8,last_error='synthetic-status',updated_at=now(),created_at=now() where id=%s",
            (kid,),
        )
        assert await baseline_llm.read(ac) == original
        for mutation in (
            "endpoint_url='https://changed.invalid/v1'",
            "scope='synthetic-changed-scope'",
            "rpd_limit=21",
            "credential_uid=gen_random_uuid()",
            "deleted_at=now()",
        ):
            before = await baseline_llm.read(ac)
            conn.execute("update llm_api_keys set " + mutation + " where id=%s", (kid,))
            assert await baseline_llm.read(ac) != before


@pytest.mark.parametrize("revoked", ["inactive", "deleted"])
async def test_frozen_approved_non_llm_remainder_survives_key_revocation_but_network_does_not(
    seeded, conn, monkeypatch, revoked
):
    import dataclasses

    from app.agent.graph import load_deps, process_signal, resume_after_human
    from app.ingest.normalizer import create_signal, from_api_signal
    from app.llm.failover import ProviderChain
    from app.llm.mock import MockProvider
    from app.sim import runs

    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    get_settings.cache_clear()
    base = "https://synthetic.invalid/v1"
    kid = conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,endpoint_url,scope) values('gigachat','synthetic',pgp_sym_encrypt('synthetic-only',%s),%s,%s) returning id",
        (get_settings().app_secret, base, get_settings().gigachat_scope),
    ).fetchone()[0]
    ids = {}
    for role in ("main", "fast", "twin"):
        ids[role] = conn.execute(
            "insert into llm_profiles(code,provider,model,role,base_url,api_key_id) values(%s,'gigachat',%s,%s,%s,%s) returning id",
            ("resume-" + role, "Frozen-" + role, role, base, kid),
        ).fetchone()[0]
    conn.execute(
        "insert into settings(key,value) values('setup_payload',%s) on conflict(key) do update set value=excluded.value",
        (Jsonb({"llm": {role + "_profile_id": pid for role, pid in ids.items()}}),),
    )

    class Recording(MockProvider):
        name = "gigachat"
        credential_id = kid
        calls = 0

        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            self.calls += 1
            obj, usage, raw = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
            return obj, dataclasses.replace(usage, model=profile.model), raw

    provider = Recording()
    chain = ProviderChain([provider], append_mock=False)
    default = LLMProfile(code="current", provider="gigachat", model="current")
    now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    cid = conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1").fetchone()[0]
    async with await connect(seeded) as ac:
        rid = await runs.create_run(ac, kind="free", label="static resume", seed=7, sim_time=now)
        result = await create_signal(
            ac,
            from_api_signal(
                {
                    "channel_code": "email",
                    "client_id": cid,
                    "text": "Третий день не могу открыть вклад, ошибка подтверждения.",
                }
            ),
            source_code="api",
            run_id=rid,
            sim_time=now,
            emit_event=False,
        )
        state = await process_signal(ac, signal_id=result["signal_id"], chain=chain, profile=default)
        assert state["outcome"] == "awaiting_human"
        arid = state["agent_run_id"]
        hid = conn.execute("select id from human_decisions where agent_run_id=%s", (arid,)).fetchone()[0]
        approved = {
            "incident_action": "none",
            "router_action": "none",
            "client_action": {"kind": "none"},
            "followup": None,
            "gift": None,
            "escalation": None,
        }
        conn.execute(
            "update human_decisions set decision='modify',modified_proposal=%s,decided_by='synthetic-operator',decided_at=now() where id=%s",
            (Jsonb(approved), hid),
        )
        conn.execute(
            "update llm_api_keys set is_active=false,deleted_at=case when %s='deleted' then now() else null end where id=%s",
            (revoked, kid),
        )
        before = provider.calls
        resumed = await resume_after_human(ac, human_decision_id=hid, chain=chain, profile=default, sim_time=now)
        assert resumed["outcome"] == "completed" and provider.calls == before
        assert conn.execute("select decision from human_decisions where id=%s", (hid,)).fetchone()[0] == "modify"
        deps = await load_deps(ac, chain=chain, profile=default, run_id=rid, agent_run_id=arid, sim_time=now)
        with pytest.raises(Problem):
            await deps.chain.complete_structured(
                [{"role": "user", "content": "fixed synthetic"}], {"type": "object"}, deps.profile
            )
        assert provider.calls == before
        with pytest.raises(Problem):
            await credentials.validate_binding(ac, deps.profile)
        with pytest.raises(Problem):
            from app.llm.run_profiles import capture

            await capture(ac, None)
    get_settings.cache_clear()
