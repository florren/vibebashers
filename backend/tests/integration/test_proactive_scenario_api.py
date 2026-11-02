"""Actual ASGI endpoint: preflight до нового run, native prepared вместо inject3."""

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from app.agent.runner import AgentService
from app.api.scenarios import router
from app.sim.engine import Simulator
from app.sim.proactive_scenario import prepared
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_proactive_prepare import mass_seeded as mass_seeded


def application(sim, service):
    app = FastAPI()
    app.state.sim = sim
    app.state.agent = service
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_api_scripted_lite_preflight_leaves_owner_clock_rng_and_run_count_unchanged(seeded):
    sim = Simulator(dsn=dsn(seeded))
    await sim.load_state()
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(seeded), sim=sim)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await (
                await conn.execute("select current_run_id,sim_time,rng_state,running from sim_state where id=1")
            ).fetchone()
            count = await (await conn.execute("select count(*) from sim_runs")).fetchone()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(sim, service)), base_url="http://synthetic.test"
        ) as client:
            response = await client.post("/api/scenarios/mass_notifications/run", json={})
        assert response.status_code == 409
        assert "insufficient_cohort" in response.text
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select current_run_id,sim_time,rng_state,running from sim_state where id=1")
                ).fetchone()
                == before
            )
            assert await (await conn.execute("select count(*) from sim_runs")).fetchone() == count
            assert not await (
                await conn.execute("select 1 from sim_events where event_type='scenario.proactive_prepared'")
            ).fetchone()
    finally:
        await service.stop()
        await sim.shutdown()


@pytest.mark.asyncio
async def test_api_scripted_demo_prepares_120_native_rows_paused_without_fake_client_or_eager_ar(mass_seeded):
    sim = Simulator(dsn=dsn(mass_seeded))
    await sim.load_state()
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(sim, service)), base_url="http://synthetic.test"
        ) as client:
            response = await client.post("/api/scenarios/mass_notifications/run", json={"reset_mode": "none"})
        assert response.status_code == 202, response.text
        body = response.json()
        run = body["run"]["id"]
        assert body["run"]["status"] == "paused"
        assert body["client_id"] is None
        assert sim.run_id == run and not sim.clock.running
        assert not service._inflight
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            receipt = await prepared(conn, run)
            assert receipt is not None and len(receipt.payload["operation_ids"]) == 120
            assert (
                await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()
            ) == (120,)
            assert not await (await conn.execute("select 1 from signals where run_id=%s", (run,))).fetchone()
            assert not await (await conn.execute("select 1 from agent_runs where sim_run_id=%s", (run,))).fetchone()
            assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
    finally:
        await service.stop()
        await sim.shutdown()
