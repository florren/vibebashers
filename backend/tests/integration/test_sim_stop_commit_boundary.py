"""Cancellation не откатывает memory поверх уже committed tick PostgreSQL."""

import asyncio
import datetime as dt

import psycopg
import pytest

from app.sim.engine import Simulator
from tests.helpers import dsn


@pytest.mark.parametrize("action", ["pause", "stop", "cancel", "cancel_twice"])
async def test_tick_commit_is_durable_before_caller_cancellation_finishes(seeded, monkeypatch, action):
    sim = Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Commit boundary", start_paused=True)
    await sim.resume_run()
    before = sim.clock.sim_time
    sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
    committed, release, stopping = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_commit = psycopg.AsyncConnection.commit
    original_stop = sim._stop_loop
    blocked = False
    commit_cancelled = []

    async def commit(conn):
        nonlocal blocked
        await original_commit(conn)
        if conn is sim.conn and not blocked:
            blocked = True
            committed.set()
            try:
                await release.wait()  # БД уже committed, Python tick ещё внутри try.
            except asyncio.CancelledError:
                commit_cancelled.append(True)
                raise

    async def stop_loop():
        stopping.set()
        await original_stop()

    async def tick_loop():
        await sim.step(1)
        await asyncio.Event().wait()  # Между ticks штатный loop тоже ждёт.

    monkeypatch.setattr(psycopg.AsyncConnection, "commit", commit)
    monkeypatch.setattr(sim, "_stop_loop", stop_loop)
    sim._task = asyncio.create_task(tick_loop())
    control = None
    try:
        await asyncio.wait_for(committed.wait(), 10)
        if action.startswith("cancel"):
            sim._task.cancel()  # Прямая отмена step/API, без _stop_loop.
            if action == "cancel_twice":
                await asyncio.sleep(0)  # Caller обрабатывает первую отмену и снова ждёт COMMIT.
                sim._task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(sim._task, 10)
        else:
            control = asyncio.create_task(sim.control(action))
            await asyncio.wait_for(stopping.wait(), 5)
            release.set()
            await asyncio.wait_for(control, 10)
        assert sim.clock.sim_time == before + dt.timedelta(minutes=1)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select st.sim_time,st.rng_state,st.running,r.status from sim_state st "
                    "join sim_runs r on r.id=st.current_run_id where st.id=1"
                )
            ).fetchone()
            assert row == (
                sim.clock.sim_time,
                sim.rng.dump_state(),
                action.startswith("cancel"),
                "running" if action.startswith("cancel") else ("paused" if action == "pause" else "stopped"),
            )
        assert sim.stats["ticks"] == 1 and not commit_cancelled
        assert (sim._task is None) is (not action.startswith("cancel"))
    finally:
        release.set()
        if sim._task is not None:
            sim._task.cancel()
        await asyncio.gather(*[task for task in (control, sim._task) if task is not None], return_exceptions=True)
        if sim.conn and not sim.conn.closed:
            await sim.conn.close()


@pytest.mark.parametrize("failure", ["error", "cancel_then_error"])
async def test_failed_commit_rolls_back_even_after_caller_cancellation(seeded, monkeypatch, failure):
    sim = Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Commit marker failure", start_paused=True)
    sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
    before, rng_before = sim.clock.sim_time, sim.rng.dump_state()
    entered, release = asyncio.Event(), asyncio.Event()
    original_commit = psycopg.AsyncConnection.commit

    async def commit(conn):
        if conn is sim.conn:
            entered.set()
            await release.wait()
            raise RuntimeError("synthetic commit failed before durability")
        await original_commit(conn)

    monkeypatch.setattr(psycopg.AsyncConnection, "commit", commit)
    tick = asyncio.create_task(sim.step(1))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        if failure == "cancel_then_error":
            tick.cancel()
        release.set()
        with pytest.raises(RuntimeError, match="synthetic commit failed"):
            await asyncio.wait_for(tick, 10)
        assert sim.clock.sim_time == before and sim.rng.dump_state() == rng_before
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()) == (
                before,
                rng_before,
            )
        monkeypatch.setattr(psycopg.AsyncConnection, "commit", original_commit)
        await sim.step(1)
        assert sim.clock.sim_time == before + dt.timedelta(minutes=1)
    finally:
        release.set()
        if not tick.done():
            tick.cancel()
        await asyncio.gather(tick, return_exceptions=True)
        if sim.conn and not sim.conn.closed:
            await sim.conn.close()
