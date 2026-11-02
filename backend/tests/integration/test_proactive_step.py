"""Scripted clock использует native atomic step; restart не повторяет RNG/owner."""

import copy
import datetime as dt

import psycopg
import pytest

from app.sim import scenarios
from app.sim.behavior.owner import BehaviorOwner
from app.sim.engine import Simulator
from app.sim.generators import World
from app.sim.proactive_scenario import ScriptedScenarioError, case, plan, prepare
from tests.helpers import dsn
from tests.integration.test_proactive_prepare import current, scenario
from tests.integration.test_proactive_prepare import mass_seeded as mass_seeded


async def setup_case(url, monkeypatch):
    raw = scenario()
    monkeypatch.setattr(scenarios, "get", lambda key: raw if key == raw["id"] else None)
    async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
        run = await current(conn)
    sim = Simulator(dsn=url)
    await sim.load_state()
    # API start сохраняет RNG до prepare; new_run helper сам clock не запускает.
    await sim.persist()
    await sim.conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
        async with conn.transaction():
            record = await prepare(conn, run, plan(raw))
    return sim, run, record


@pytest.mark.asyncio
async def test_native_prepared_step_preserves_owner_and_is_exactly_once_after_reload(mass_seeded, monkeypatch):
    sim, run, record = await setup_case(mass_seeded, monkeypatch)

    async def ambient_bomb(*args, **kwargs):
        raise AssertionError("prepared mode не вызывает ambient source")

    for method in ("gen_faults", "gen_operations", "gen_client_errors"):
        monkeypatch.setattr(World, method, ambient_bomb)
    original = World.flush_signals
    calls = []

    async def flush(world, now, minutes, *, ambient_noise=True):
        calls.append(ambient_noise)
        return await original(world, now, minutes, ambient_noise=ambient_noise)

    monkeypatch.setattr(World, "flush_signals", flush)
    target = record.at + dt.timedelta(minutes=1)
    try:
        assert await sim.prepared_step(run, record.at, target) is True
        assert calls == [False]
        assert sim.stats["ticks"] == 1 and sim.stats["ops"] == 0
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert (await case(conn, run)).initial_at == target
            assert await (
                await conn.execute("select count(*) from behavior_runtime where run_id=%s", (run,))
            ).fetchone() == (120,)
            assert not await (await conn.execute("select 1 from signals where run_id=%s", (run,))).fetchone()
            assert (
                await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()
            ) == (120,)
            before = await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()
        # Discard owner после committed clock, до later phase receipt.
        await sim.shutdown()
        sim = Simulator(dsn=mass_seeded)
        await sim.load_state()
        assert await sim.prepared_step(run, record.at, target) is False
        assert calls == [False]
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert (
                await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone() == before
            )
        with pytest.raises(ScriptedScenarioError, match="phase_clock_changed"):
            await sim.prepared_step(run, target, target + dt.timedelta(minutes=0.1))
    finally:
        await sim.shutdown()


@pytest.mark.asyncio
async def test_prepared_owner_failure_rolls_back_clock_rng_episodes_and_retry(mass_seeded, monkeypatch):
    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    original = BehaviorOwner.advance

    async def broken(owner, *args, **kwargs):
        await original(owner, *args, **kwargs)
        raise RuntimeError("synthetic owner failure after native work")

    target = record.at + dt.timedelta(minutes=1)
    before_rng, before_stats = sim.rng.dump_state(), dict(sim.stats)
    try:
        monkeypatch.setattr(BehaviorOwner, "advance", broken)
        with pytest.raises(RuntimeError, match="synthetic owner failure"):
            await sim.prepared_step(run, record.at, target)
        assert sim.clock.sim_time == record.at and sim.rng.dump_state() == before_rng and sim.stats == before_stats
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone()) == (record.at,)
            assert not await (
                await conn.execute("select 1 from behavior_runtime where run_id=%s", (run,))
            ).fetchone()
            assert not await (
                await conn.execute("select 1 from sim_events where run_id=%s and event_type like 'client.%%'", (run,))
            ).fetchone()
        monkeypatch.setattr(BehaviorOwner, "advance", original)
        assert await sim.prepared_step(run, record.at, target) is True
    finally:
        await sim.shutdown()


@pytest.mark.asyncio
async def test_prepared_step_rejects_changed_script_before_clock_or_owner(mass_seeded, monkeypatch):
    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    changed = copy.deepcopy(scenarios.get("mass_notifications"))
    changed["complaint_templates"][0]["text"] += " Другое описание."
    monkeypatch.setattr(scenarios, "get", lambda key: changed)
    try:
        with pytest.raises(ScriptedScenarioError, match="script_changed"):
            await sim.prepared_step(run, record.at, record.at + dt.timedelta(minutes=1))
        assert sim.stats["ticks"] == 0 and sim.clock.sim_time == record.at
    finally:
        await sim.shutdown()
