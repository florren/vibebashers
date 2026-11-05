"""Global Start действительно тикает World; Journey/demo профиль не выключает native teams."""

from __future__ import annotations

import asyncio

import psycopg
import pytest

from app.demo.settings import configuration, save
from app.sim.engine import Simulator
from tests.helpers import dsn

pytestmark = pytest.mark.integration


async def committed_ticks(seeded, sim, after, count):
    times = []
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as observer:
        async with asyncio.timeout(15):
            while len(times) < count:
                value = (await (await observer.execute("select sim_time from sim_state where id=1")).fetchone())[0]
                if value > after and (not times or value > times[-1]):
                    times.append(value)
                await asyncio.sleep(0.02)
    return times


async def test_global_start_native_loop_commits_twice_and_controls_preserve_owner(seeded, monkeypatch):
    from app.sim.teams import TeamEmulator

    sim = Simulator(dsn=seeded)
    sim.full_execution = True
    sim._intensities = dict(op=4000, fault=0, client_error=0, signal_noise=0)
    native_calls = []
    original = TeamEmulator.tick

    async def observe(self, at, world):
        if sim.world is not None and self is sim.world.team_emulator:
            native_calls.append((at, world is sim.world))
        return await original(self, at, world)

    monkeypatch.setattr(TeamEmulator, "tick", observe)
    await sim.load_state()
    try:
        before = sim.clock.sim_time
        await sim.control("start", label="Whole-world native Start", speed=120)
        rid = sim.run_id
        assert sim._task is not None and not sim._task.done()
        times = await committed_ticks(seeded, sim, before, 2)
        assert len(times) == 2 and times[1] > times[0]
        await sim.control("pause")
        paused = sim.clock.sim_time
        assert not sim.clock.running and sim._task is None and sim.run_id == rid
        assert len(native_calls) >= 2 and all(owned for _, owned in native_calls)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            config = await configuration(conn, rid)
            assert config["mode"] == "simulation" and config["scenario_id"] is None
            assert (await (await conn.execute("select count(*) from operations where run_id=%s", (rid,))).fetchone())[
                0
            ] > 0
        await sim.control("resume")
        assert sim._task is not None and not sim._task.done() and sim.run_id == rid
        await committed_ticks(seeded, sim, paused, 1)
        await sim.control("stop")
        assert sim._task is None and not sim.clock.running and sim.run_id == rid
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select st.sim_time,st.running,r.status from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1"
                )
            ).fetchone()
            assert row == (sim.clock.sim_time, False, "stopped")
    finally:
        await sim.shutdown()


async def test_legacy_isolated_demo_keeps_native_team_tick_disabled(seeded, monkeypatch):
    from app.sim.teams import TeamEmulator

    sim = Simulator(dsn=seeded)
    sim._intensities = dict(op=0, fault=0, client_error=0, signal_noise=0)
    await sim.load_state()
    try:
        await sim.control("start", label="Legacy isolated demo", start_paused=True)
        await save(sim.conn, sim.run_id, {"mode": "demo", "enabled": True})
        await sim.conn.commit()
        calls = []
        original = TeamEmulator.tick

        async def observe(self, at, world):
            calls.append(at)
            return await original(self, at, world)

        monkeypatch.setattr(TeamEmulator, "tick", observe)
        await sim.step(1)
        assert calls == []
    finally:
        await sim.shutdown()
