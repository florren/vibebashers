"""T-040: профиль запуска переживает смену глобальных/DB настроек без live calls."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent.graph import load_deps
from app.config import get_settings
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.llm.run_profiles import resolve
from app.sim import runs

pytestmark = pytest.mark.integration


@pytest.fixture
def online_mode(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_all_role_snapshots_are_pinned_and_chain_is_not_mutated(seeded, conn, online_mode):
    ids = {}
    for role in ("main", "fast", "twin"):
        ids[role] = conn.execute(
            "insert into llm_profiles(code,provider,model,role) values(%s,'gigachat',%s,%s) returning id",
            (f"pin-{role}", f"Pinned-{role}", role),
        ).fetchone()[0]
    conn.execute(
        "insert into settings(key,value) values('setup_payload',%s) on conflict(key) do update set value=excluded.value",
        (Jsonb({"llm": {f"{role}_profile_id": pid for role, pid in ids.items()}}),),
    )
    default = LLMProfile(code="global", provider="gigachat", model="Global-main")
    chain = ProviderChain([SimpleNamespace(name="gigachat")])
    chain.role_profiles = {"fast": dataclasses.replace(default, model="Global-fast", role="fast")}
    now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    async with await psycopg.AsyncConnection.connect(
        seeded.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as ac:
        rid = await runs.create_run(ac, kind="free", label="pinned", seed=9, sim_time=now, llm_profile_id=ids["main"])
        conn.execute(
            "update llm_profiles set model='Changed-later',price_in_per_1m=9,price_out_per_1m=9 where id=any(%s)",
            (list(ids.values()),),
        )
        scoped, main = await resolve(ac, rid, chain, default)
        assert main.model == "Pinned-main"
        assert {role: profile.model for role, profile in scoped.role_profiles.items()} == {
            role: f"Pinned-{role}" for role in ids
        }
        assert chain.role_profiles["fast"].model == "Global-fast"
        assert scoped.providers is chain.providers
        assert scoped.role_profile_ids == ids and scoped.role_profiles_pinned
        assert chain.role_profile_ids == {} and not chain.role_profiles_pinned
        deps = await load_deps(ac, chain=chain, profile=default, run_id=rid, agent_run_id=0, sim_time=now)
        assert deps.profile.model == "Pinned-main" and deps.fast_profile.model == "Pinned-fast"
        assert deps.profile.price_in_per_1m == 0 and deps.profile.price_out_per_1m == 0
        assert deps.chain is not chain
        await ac.execute(
            "insert into agent_runs(kind,sim_run_id,llm_profile_id,prompt_version,prompt_tokens,completion_tokens,total_tokens,cost_estimate) values('agent',%s,%s,'test',60,40,100,0.1234)",
            (rid, ids["main"]),
        )
        from app.sim.run_summary import build_summary

        summary = await build_summary(ac, rid)
        usage = summary["llm_profiles"][0]
        assert usage["model"] == "Pinned-main" and usage["tariff_source"] == "run_snapshot"
        assert usage["tariff_cost_estimate"] == 0
        assert usage["recorded_cost_estimate"] == 0.1234


async def test_runtime_mock_disables_every_live_provider_for_saved_run(seeded, conn, monkeypatch):
    from app.llm.run_profiles import ROLES

    live = {
        role: dataclasses.asdict(LLMProfile(code=role, provider="gigachat", model=role, role=role)) for role in ROLES
    }
    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,status,started_sim,settings_snapshot) values('free','offline',1,'completed',now(),%s) returning id",
        (Jsonb({"llm_profiles": {"version": 1, "roles": live}}),),
    ).fetchone()[0]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    chain = ProviderChain([SimpleNamespace(name="gigachat"), MockProvider()])
    default = LLMProfile(code="x", provider="gigachat", model="x")
    try:
        async with await psycopg.AsyncConnection.connect(
            seeded.replace("postgresql+psycopg://", "postgresql://")
        ) as ac:
            scoped, main = await resolve(ac, rid, chain, default)
        assert main.provider == "mock"
        assert {profile.provider for profile in scoped.role_profiles.values()} == {"mock"}
        assert scoped.names == ["mock"] and chain.names == ["gigachat", "mock"]
    finally:
        get_settings.cache_clear()
