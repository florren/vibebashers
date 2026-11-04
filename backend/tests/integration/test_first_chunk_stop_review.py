"""Stop после preflight target не должен создавать новый неявный free run."""

import asyncio
import datetime as dt

import httpx
import psycopg
import pytest

from app.config import get_settings
from app.main import create_app
from tests.helpers import dsn
from tests.integration.test_behavior_runtime import setup


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["jump_to", "reset_day"])
async def test_stop_after_target_preflight_before_first_owned_chunk(seeded, monkeypatch, action):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, before, sim = await setup(conn, monkeypatch, seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    if sim.run_status in ("paused", "interrupted"):
        await sim.resume_run()
    assert sim.run_status == "running"
    rng_before = sim.rng.dump_state()
    entered, release = asyncio.Event(), asyncio.Event()
    original = sim._step_to

    async def gated(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(sim, "_step_to", gated)
    app = create_app()
    app.state.sim = sim
    task = None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://own.local") as api:
            body = {"action": action}
            if action == "jump_to":
                body["sim_time"] = (before + dt.timedelta(minutes=65)).isoformat()
            task = asyncio.create_task(api.post("/api/sim/control", json=body))
            await asyncio.wait_for(entered.wait(), 10)
            stop = await api.post("/api/sim/control", json={"action": "stop"})
            assert stop.status_code == 200, stop.text
            assert sim.run_status == "stopped" and sim.run_id == run and sim.clock.sim_time == before
            release.set()
            response = await asyncio.wait_for(task, 45)
            evidence = {
                "action": action,
                "old_run": run,
                "response": response.status_code,
                "body": response.json(),
                "after_run": sim.run_id,
                "after_status": sim.run_status,
                "advance_minutes": (sim.clock.sim_time - before).total_seconds() / 60,
            }
            assert response.status_code == 409, evidence
            assert sim.run_id == run and sim.run_status == "stopped" and sim.clock.sim_time == before, evidence
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as observer:
                row = await (
                    await observer.execute(
                        "select st.current_run_id,st.sim_time,st.rng_state,r.status from sim_state st "
                        "join sim_runs r on r.id=st.current_run_id where st.id=1"
                    )
                ).fetchone()
                assert row == (run, before, rng_before, "stopped")
    finally:
        release.set()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        if sim.conn:
            await sim.conn.close()
