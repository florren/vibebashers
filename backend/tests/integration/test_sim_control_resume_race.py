"""HTTP Start после конкурентной Pause должен штатно возобновить тот же run."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

import httpx
import psycopg
import pytest

from app.config import get_settings
from app.main import create_app
from app.sim import engine
from tests.helpers import dsn

ACTOR: ContextVar[str] = ContextVar("sim-resume-test-actor", default="")


@pytest.mark.asyncio
@pytest.mark.parametrize("barrier", ["pause_write", "after_start_preflight"])
@pytest.mark.parametrize("mode", ["simulation", "demo"])
async def test_http_start_rechecks_resume_at_mutation_boundary(seeded, monkeypatch, barrier, mode):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    sim = engine.Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Concurrent API pause/start")
    run, before = sim.run_id, sim.clock.sim_time
    if mode == "demo":
        from app.demo.settings import save

        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await save(conn, run, {"mode": "demo", "enabled": True, "status": "running"})
    hooks = []

    async def before_resume(run_id, at):
        hooks.append(("before", run_id, at))

    async def after_resume(run_id, at):
        hooks.append(("after", run_id, at))

    sim.before_resume, sim.after_resume = before_resume, after_resume
    app = create_app()
    app.state.sim = sim
    entered, waiting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    inner = sim._lock

    class DispatchLock:
        first_start_exit = True

        async def __aenter__(self):
            if ACTOR.get() == "start" and inner.locked():
                waiting.set()
            await inner.acquire()
            return self

        async def __aexit__(self, *_args):
            inner.release()
            if barrier == "after_start_preflight" and ACTOR.get() == "start" and self.first_start_exit:
                self.first_start_exit = False
                # SELECT/preflight завершён; между ним и mutation branch возможна Pause.
                entered.set()
                await release.wait()

    sim._lock = DispatchLock()
    original_status = engine.run_svc.set_run_status

    async def blocked_status(conn, run_id, status, *args, **kwargs):
        result = await original_status(conn, run_id, status, *args, **kwargs)
        if barrier == "pause_write" and ACTOR.get() == "pause" and status == "paused":
            # Реальная запись уже в TX, но memory run_status ещё running.
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(engine.run_svc, "set_run_status", blocked_status)
    tasks = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:

            async def post(actor, action):
                token = ACTOR.set(actor)
                try:
                    return await api.post("/api/sim/control", json={"action": action})
                finally:
                    ACTOR.reset(token)

            if barrier == "pause_write":
                pause = asyncio.create_task(post("pause", "pause"))
                tasks.append(pause)
                await asyncio.wait_for(entered.wait(), 10)
                assert sim.run_status == "running"
                start = asyncio.create_task(post("start", "start"))
                tasks.append(start)
                await asyncio.wait_for(waiting.wait(), 10)
                release.set()
                paused, started = await asyncio.wait_for(asyncio.gather(pause, start), 20)
            else:
                start = asyncio.create_task(post("start", "start"))
                tasks.append(start)
                await asyncio.wait_for(entered.wait(), 10)
                pause = asyncio.create_task(post("pause", "pause"))
                tasks.append(pause)
                paused = await asyncio.wait_for(pause, 10)
                assert sim.run_status == "paused"
                release.set()
                started = await asyncio.wait_for(start, 20)
            assert paused.status_code == started.status_code == 200, (paused.text, started.text)
            assert started.json()["current_run_status"] == "running" and started.json()["running"] is True
        assert sim.run_id == run and sim.run_status == "running" and sim.clock.running
        assert hooks == [("before", run, before), ("after", run, before)]
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select st.current_run_id,st.running,st.sim_time,r.status,r.resumed_count "
                    "from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1"
                )
            ).fetchone()
            assert row == (run, True, before, "running", 1)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
async def test_http_demo_stop_between_start_phases_keeps_finished_run_and_starts_new(seeded, monkeypatch):
    from app.demo.settings import configuration, save

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    sim = engine.Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Demo before concurrent Stop")
    old_run = sim.run_id
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        await save(conn, old_run, {"mode": "demo", "enabled": True, "status": "running"})
    app = create_app()
    app.state.sim = sim
    entered, release = asyncio.Event(), asyncio.Event()
    inner = sim._lock

    class PreflightGap:
        first_start_exit = True

        async def __aenter__(self):
            await inner.acquire()
            return self

        async def __aexit__(self, *_args):
            inner.release()
            if ACTOR.get() == "start" and self.first_start_exit:
                self.first_start_exit = False
                entered.set()
                await release.wait()

    sim._lock = PreflightGap()
    start = None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:

            async def request_start():
                token = ACTOR.set("start")
                try:
                    return await api.post("/api/sim/control", json={"action": "start"})
                finally:
                    ACTOR.reset(token)

            start = asyncio.create_task(request_start())
            await asyncio.wait_for(entered.wait(), 10)
            stopped = await api.post("/api/sim/control", json={"action": "stop"})
            assert stopped.status_code == 200 and sim.run_status == "stopped"
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                finished = await (
                    await conn.execute(
                        "select status,finished_sim,finished_at,resumed_count from sim_runs where id=%s", (old_run,)
                    )
                ).fetchone()
                stopped_profile = await configuration(conn, old_run)
                assert finished[0] == "stopped" and finished[1] is not None and finished[2] is not None
                assert stopped_profile["enabled"] is False
            release.set()
            started = await asyncio.wait_for(start, 15)
            assert started.status_code == 200, started.text
        assert sim.run_id != old_run and sim.run_status == "running" and sim.clock.running
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute(
                        "select status,finished_sim,finished_at,resumed_count from sim_runs where id=%s", (old_run,)
                    )
                ).fetchone()
            ) == finished
            assert await configuration(conn, old_run) == stopped_profile
            assert (
                await (await conn.execute("select current_run_id,running from sim_state where id=1")).fetchone()
            ) == (sim.run_id, True)
    finally:
        release.set()
        if start is not None:
            await asyncio.gather(start, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,halt", [("simulation", "pause"), ("demo", "pause"), ("demo", "stop")])
async def test_late_start_releases_guard_row_before_waiting_for_queued_worker(seeded, monkeypatch, mode, halt):
    from app.demo.settings import save

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    sim = engine.Simulator(dsn=seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    await sim.control("start", label="Guard row and queued native worker")
    old_run = sim.run_id
    if mode == "demo":
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await save(conn, old_run, {"mode": "demo", "enabled": True, "status": "running"})
    app = create_app()
    app.state.sim = sim
    preflight, continue_start, selected, worker_waiting = (asyncio.Event() for _ in range(4))
    inner = sim._lock

    class GuardGap:
        start_exits = 0

        async def __aenter__(self):
            if ACTOR.get() == "worker" and inner.locked():
                worker_waiting.set()
            await inner.acquire()
            return self

        async def __aexit__(self, *_args):
            if ACTOR.get() == "start":
                self.start_exits += 1
                if self.start_exits == 1:
                    inner.release()
                    preflight.set()
                    await continue_start.wait()
                    return
                if self.start_exits == 2:
                    # Worker уже ждёт Python lock до следующего resume/start acquire.
                    selected.set()
                    await worker_waiting.wait()
            inner.release()

    sim._lock = GuardGap()
    tasks = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:

            async def request_start():
                token = ACTOR.set("start")
                try:
                    return await api.post("/api/sim/control", json={"action": "start"})
                finally:
                    ACTOR.reset(token)

            async def queued_worker():
                token = ACTOR.set("worker")
                try:
                    async with sim._lock:
                        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                            await conn.execute("select id from sim_state where id=1 for update")
                finally:
                    ACTOR.reset(token)

            start = asyncio.create_task(request_start())
            tasks.append(start)
            await asyncio.wait_for(preflight.wait(), 10)
            halted = await api.post("/api/sim/control", json={"action": halt})
            assert halted.status_code == 200
            continue_start.set()
            await asyncio.wait_for(selected.wait(), 10)
            worker = asyncio.create_task(queued_worker())
            tasks.append(worker)
            # Guard row не должен оставаться у Start пока он ждёт lock у worker.
            result, _ = await asyncio.wait_for(asyncio.gather(start, worker), 5)
            assert result.status_code == 200, result.text
        assert sim.run_status == "running" and sim.clock.running
        assert (sim.run_id == old_run) is (halt == "pause")
    finally:
        continue_start.set()
        worker_waiting.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()
