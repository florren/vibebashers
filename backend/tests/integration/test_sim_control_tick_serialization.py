"""Один Simulator: control не читает и не откатывает незавершённый tick."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest

from app.sim.engine import Simulator
from tests.helpers import dsn


class ObservedLock:
    """Событие фиксирует реальную попытку control занять lock, без sleep-гонки."""

    def __init__(self, lock, waiting):
        self.lock = lock
        self.waiting = waiting

    async def __aenter__(self):
        if asyncio.current_task().get_name() == "control-during-tick" and self.lock.locked():
            self.waiting.set()
        await self.lock.acquire()
        return self

    async def __aexit__(self, *_args):
        self.lock.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("action,cancel", [("start", False), ("set_speed", False), ("start", True)])
async def test_control_serializes_with_native_tick_before_reading_shared_connection(
    seeded, monkeypatch, action, cancel
):
    sim = Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Tick owner before concurrent control", start_paused=True)
    run, before = sim.run_id, sim.clock.sim_time
    sim._intensities = {"op": 4000, "fault": 0, "client_error": 0, "signal_noise": 0}
    entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sim._lock = ObservedLock(sim._lock, waiting)
    original_persist = sim.persist
    first_persist = True

    async def blocked_persist():
        nonlocal first_persist
        if asyncio.current_task().get_name() == "native-blocked-tick" and first_persist:
            first_persist = False
            # gen_operations уже записал native факты/RNG, часы продвинуты,
            # но sim_state и общий commit ещё не выполнены.
            assert (
                await (await sim.conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()
            )[0] > 0
            entered.set()
            await release.wait()
        await original_persist()

    monkeypatch.setattr(sim, "persist", blocked_persist)
    tick = asyncio.create_task(sim.step(15), name="native-blocked-tick")
    control = observed = None
    try:
        await asyncio.wait_for(entered.wait(), 10)
        assert sim.clock.sim_time == before + dt.timedelta(minutes=15)
        options = {"label": "Next run after complete tick", "start_paused": True} if action == "start" else {"speed": 7}
        control = asyncio.create_task(sim.control(action, **options), name="control-during-tick")
        observed = asyncio.create_task(waiting.wait())
        await asyncio.wait_for(asyncio.wait([control, observed], return_when=asyncio.FIRST_COMPLETED), 10)
        assert waiting.is_set() and not control.done(), (
            "control must await the active tick before shared-connection I/O"
        )
        if cancel:
            control.cancel()
            with pytest.raises(asyncio.CancelledError):
                await control
        release.set()
        await asyncio.wait_for(tick, 15)
        if not cancel:
            await asyncio.wait_for(control, 10)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute("select count(*),max(started_sim) from operations where run_id=%s", (run,))
            ).fetchone()
            assert rows[0] > 0 and rows[1] <= before + dt.timedelta(minutes=15)
            clock = await (
                await conn.execute("select current_run_id,sim_time,rng_state from sim_state where id=1")
            ).fetchone()
            assert clock == (sim.run_id, before + dt.timedelta(minutes=15), sim.rng.dump_state())
            if action == "start" and not cancel:
                assert sim.run_id != run
                assert (
                    await (await conn.execute("select started_sim from sim_runs where id=%s", (sim.run_id,))).fetchone()
                ) == (before + dt.timedelta(minutes=15),)
            else:
                assert sim.run_id == run
    finally:
        release.set()
        if observed is not None and not observed.done():
            observed.cancel()
        await asyncio.gather(*[task for task in (tick, control, observed) if task is not None], return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
async def test_post_step_persist_and_commit_keep_connection_owned_until_complete(seeded, monkeypatch):
    sim = Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Post-step connection owner", start_paused=True)
    before = sim.clock.sim_time
    sim._intensities = {"op": 4000, "fault": 0, "client_error": 0, "signal_noise": 0}
    entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sim._lock = ObservedLock(sim._lock, waiting)
    original_persist, original_publish = sim.persist, sim._publish_tick
    tick_committed = False

    async def published_tick():
        nonlocal tick_committed
        await original_publish()
        if asyncio.current_task().get_name() == "post-step-control":
            tick_committed = True

    async def blocked_persist():
        await original_persist()
        if asyncio.current_task().get_name() == "post-step-control" and tick_committed:
            # Tick уже committed/published; UPDATE принадлежит завершающему control.
            entered.set()
            await release.wait()

    monkeypatch.setattr(sim, "_publish_tick", published_tick)
    monkeypatch.setattr(sim, "persist", blocked_persist)
    control = asyncio.create_task(sim.control("step", step_minutes=1), name="post-step-control")
    tick = observed = None
    try:
        await asyncio.wait_for(entered.wait(), 10)
        tick = asyncio.create_task(sim.step(1), name="control-during-tick")
        observed = asyncio.create_task(waiting.wait())
        await asyncio.wait_for(asyncio.wait([tick, observed], return_when=asyncio.FIRST_COMPLETED), 10)
        assert waiting.is_set() and not tick.done(), "next tick must wait for the control commit"
        release.set()
        await asyncio.wait_for(asyncio.gather(control, tick), 15)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()) == (
                before + dt.timedelta(minutes=2),
                sim.rng.dump_state(),
            )
            assert sim.stats["ticks"] == 2
    finally:
        release.set()
        if observed is not None and not observed.done():
            observed.cancel()
        await asyncio.gather(*[t for t in (control, tick, observed) if t is not None], return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
async def test_reset_day_policy_read_does_not_overlap_native_tick(seeded, monkeypatch):
    from app.sim import engine

    sim = Simulator(dsn=seeded)
    # Legacy policy=None — поддержанный путь reset_day без behavior шагов.
    sim.behavior_policy = None
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Reset-day connection owner", start_paused=True)
    sim._intensities = {"op": 4000, "fault": 0, "client_error": 0, "signal_noise": 0}
    entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sim._lock = ObservedLock(sim._lock, waiting)
    original_policy = engine.effective_policy

    async def blocked_policy(*args):
        if asyncio.current_task().get_name() == "reset-day-control":
            entered.set()
            await release.wait()
        return await original_policy(*args)

    monkeypatch.setattr(engine, "effective_policy", blocked_policy)
    control = asyncio.create_task(sim.control("reset_day"), name="reset-day-control")
    tick = observed = None
    try:
        await asyncio.wait_for(entered.wait(), 10)
        tick = asyncio.create_task(sim.step(1), name="control-during-tick")
        observed = asyncio.create_task(waiting.wait())
        await asyncio.wait_for(asyncio.wait([tick, observed], return_when=asyncio.FIRST_COMPLETED), 10)
        assert waiting.is_set() and not tick.done(), "reset policy query must own the shared connection"
        release.set()
        await asyncio.wait_for(asyncio.gather(control, tick), 15)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()) == (
                sim.clock.sim_time,
                sim.rng.dump_state(),
            )
            assert sim.stats["ticks"] == 1
    finally:
        release.set()
        if observed is not None and not observed.done():
            observed.cancel()
        await asyncio.gather(*[t for t in (control, tick, observed) if t is not None], return_exceptions=True)
        if sim.conn:
            await sim.conn.close()
