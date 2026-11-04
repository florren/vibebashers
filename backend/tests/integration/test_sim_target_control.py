"""Concurrent HTTP controls: target advance учитывает уже выполненный чужой step."""

from __future__ import annotations

import asyncio
import datetime as dt
from contextvars import ContextVar

import httpx
import psycopg
import pytest

from app.config import get_settings
from app.main import create_app
from app.sim import engine
from app.sim.clock import MSK
from tests.helpers import dsn
from tests.integration.test_behavior_runtime import setup

ACTOR: ContextVar[str] = ContextVar("sim-target-test-actor", default="")


class TargetLock:
    def __init__(self, inner, peer_waiting):
        self.inner, self.peer_waiting = inner, peer_waiting

    async def __aenter__(self):
        if ACTOR.get() == "peer" and self.inner.locked():
            self.peer_waiting.set()
        await self.inner.acquire()
        return self

    async def __aexit__(self, *_args):
        self.inner.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["reset_day", "jump_to"])
async def test_concurrent_http_step_inside_target_progress_does_not_overshoot(seeded, monkeypatch, action):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        before = (now.astimezone(MSK) + dt.timedelta(days=1)).replace(hour=23, minute=55, second=0, microsecond=0)
        target = (
            (before + dt.timedelta(days=1)).replace(hour=9, minute=0)
            if action == "reset_day"
            else before + dt.timedelta(minutes=125)
        )
        sim.clock.sim_time = before
        await sim.persist()
        await sim.conn.commit()
    app = create_app()
    app.state.sim = sim
    entered, release, peer_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sim._lock = TargetLock(sim._lock, peer_waiting)
    hook_name = "effective_policy" if action == "reset_day" else "configuration"
    original_hook = getattr(engine, hook_name)
    first = True
    chunks = []

    async def gated_hook(*args, **kwargs):
        nonlocal first
        if ACTOR.get() == "target" and first:
            first = False
            entered.set()
            await release.wait()
        return await original_hook(*args, **kwargs)

    original_chunk = sim._step_chunk_locked

    async def observed_chunk(minutes):
        at = sim.clock.sim_time
        await original_chunk(minutes)
        chunks.append((ACTOR.get(), at, sim.clock.sim_time, minutes))

    monkeypatch.setattr(engine, hook_name, gated_hook)
    monkeypatch.setattr(sim, "_step_chunk_locked", observed_chunk)
    tasks = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:

            async def post(actor, body):
                token = ACTOR.set(actor)
                try:
                    return await api.post("/api/sim/control", json=body)
                finally:
                    ACTOR.reset(token)

            target_body = {"action": action}
            if action == "jump_to":
                target_body["sim_time"] = target.isoformat()
            control = asyncio.create_task(post("target", target_body))
            tasks.append(control)
            await asyncio.wait_for(entered.wait(), 10)
            peer = asyncio.create_task(post("peer", {"action": "step", "step_minutes": 1}))
            tasks.append(peer)
            await asyncio.wait_for(peer_waiting.wait(), 10)
            release.set()
            response, second = await asyncio.wait_for(asyncio.gather(control, peer), 45)
            assert response.status_code == second.status_code == 200, (response.text, second.text)
        target_indices = [i for i, item in enumerate(chunks) if item[0] == "target"]
        peer_indices = [i for i, item in enumerate(chunks) if item[0] == "peer"]
        assert len(target_indices) >= 2 and len(peer_indices) == 1
        # Чужой step случился внутри target advancement, а не после его завершения.
        assert min(target_indices) < peer_indices[0] < max(target_indices), chunks
        assert chunks[peer_indices[0]][3] == 1
        assert all(
            0 < minutes <= 60 and end - start == dt.timedelta(minutes=minutes) for _, start, end, minutes in chunks
        )
        assert sim.clock.sim_time == target, chunks
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select current_run_id,sim_time,rng_state from sim_state where id=1")
                ).fetchone()
            ) == (run, target, sim.rng.dump_state())
        assert sim.stats["ticks"] == len(chunks)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_action", ["start", "stop"])
async def test_http_target_rejects_new_run_between_native_chunks(seeded, monkeypatch, replacement_action):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        old_run, _, before, sim = await setup(conn, monkeypatch, seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    sim._intensities = {"op": 400, "fault": 0, "client_error": 0, "signal_noise": 0}
    app = create_app()
    app.state.sim = sim
    entered, release = asyncio.Event(), asyncio.Event()
    original_publish = sim._publish_tick
    first = True

    async def published_chunk():
        nonlocal first
        await original_publish()
        if ACTOR.get() == "target" and first:
            first = False
            entered.set()
            await release.wait()

    monkeypatch.setattr(sim, "_publish_tick", published_chunk)
    task = None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:

            async def jump():
                token = ACTOR.set("target")
                try:
                    return await api.post(
                        "/api/sim/control",
                        json={"action": "jump_to", "sim_time": (before + dt.timedelta(minutes=125)).isoformat()},
                    )
                finally:
                    ACTOR.reset(token)

            task = asyncio.create_task(jump())
            await asyncio.wait_for(entered.wait(), 10)
            committed = sim.clock.sim_time
            assert committed == before + dt.timedelta(minutes=60)
            body = (
                {"action": "start", "label": "Different run owns clock"}
                if replacement_action == "start"
                else {"action": "stop"}
            )
            replacement = await api.post("/api/sim/control", json=body)
            assert replacement.status_code == 200
            assert (sim.run_id != old_run) is (replacement_action == "start")
            current_run, rng = sim.run_id, sim.rng.dump_state()
            release.set()
            response = await asyncio.wait_for(task, 10)
            assert response.status_code == 409 and "устарел" in response.text
        assert sim.run_id == current_run and sim.clock.sim_time == committed and sim.rng.dump_state() == rng
        if replacement_action == "start":
            assert sim.stats["ticks"] == 0 and sim.world is None
        else:
            assert sim.stats["ticks"] == 1 and sim.run_status == "stopped"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select current_run_id,sim_time,rng_state from sim_state where id=1")
                ).fetchone()
            ) == (current_run, committed, rng)
            count = (
                await (await conn.execute("select count(*) from operations where run_id=%s", (current_run,))).fetchone()
            )[0]
            assert count == 0 if replacement_action == "start" else count > 0
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
async def test_cancel_target_between_committed_chunks_preserves_clock_rng_and_next_tick(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, before, sim = await setup(conn, monkeypatch, seeded)
    sim._intensities = {"op": 400, "fault": 0, "client_error": 0, "signal_noise": 0}
    initial_rng = sim.rng.dump_state()
    entered, release = asyncio.Event(), asyncio.Event()
    original_publish = sim._publish_tick
    first = True

    async def published_chunk():
        nonlocal first
        await original_publish()
        if first:
            first = False
            entered.set()
            await release.wait()

    monkeypatch.setattr(sim, "_publish_tick", published_chunk)
    task = asyncio.create_task(sim.control("jump_to", sim_time=before + dt.timedelta(minutes=125)))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        committed, rng = sim.clock.sim_time, sim.rng.dump_state()
        assert committed == before + dt.timedelta(minutes=60) and rng != initial_rng
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select current_run_id,sim_time,rng_state from sim_state where id=1")
                ).fetchone()
            ) == (run, committed, rng)
        await sim.step(1)
        assert sim.clock.sim_time == committed + dt.timedelta(minutes=1) and sim.stats["ticks"] == 2
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", [None, "stopped", "completed", "archived"])
async def test_http_jump_implicitly_creates_first_owner_without_losing_pin(seeded, monkeypatch, initial_status):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    sim = engine.Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    if initial_status is None:
        await sim.conn.execute("update sim_state set current_run_id=null,running=false where id=1")
        await sim.conn.commit()
    else:
        await sim.control("start", label="Inactive owner before target", start_paused=True)
        await engine.run_svc.set_run_status(sim.conn, sim.run_id, initial_status, sim.clock.sim_time)
        await sim.conn.commit()
    await sim.conn.close()
    sim = engine.Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    previous_run, before = sim.run_id, sim.clock.sim_time
    sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
    target = before + dt.timedelta(minutes=125)
    app = create_app()
    app.state.sim = sim
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:
            response = await api.post("/api/sim/control", json={"action": "jump_to", "sim_time": target.isoformat()})
            assert response.status_code == 200, response.text
        assert sim.run_id != previous_run and sim.clock.sim_time == target and sim.stats["ticks"] == 3
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select st.current_run_id,st.sim_time,st.rng_state,r.kind from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1"
                )
            ).fetchone()
            assert row == (sim.run_id, target, sim.rng.dump_state(), "free")
    finally:
        if sim.conn:
            await sim.conn.close()
