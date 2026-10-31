"""#133: принятый анонимный HITL продолжает команду, но не обходит другое ожидание."""

import asyncio

import psycopg
import pytest
from starlette.requests import Request

from app.agent.graph import resume_after_human
from app.agent.runner import AgentService
from app.agent.tools.base import ToolContext
from app.agent.tools.write import resume_approved_incident
from app.api.demo_execution import DemoExecutionBody, post_demo_execution
from app.config import get_settings
from app.demo.execution import cycle
from app.main import create_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, run_agent_on, sim_now

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("other_pending", [False, True])
async def test_approved_anonymous_handoff_reaches_final(seeded, monkeypatch, other_pending):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid = await new_run(conn, "approved anonymous handoff")
            # Строгий порог воспроизводит реальный low_confidence без внешней LLM.
            await conn.execute(
                "insert into settings(key,value) values ('policies','{\"confidence_threshold\":0.99}'::jsonb) "
                "on conflict(key) do update set value=settings.value || excluded.value"
            )
            sid, state = await run_agent_on(
                conn,
                "Всё не работает, разберитесь с моим обращением.",
                client_id=None,
                run_id=rid,
                origin="landing",
                channel="landing",
            )
            assert state["outcome"] == "awaiting_human"
            arid = state["agent_run_id"]
            hid, iid = await (
                await conn.execute("select id,incident_id from human_decisions where agent_run_id=%s", (arid,))
            ).fetchone()
            assert iid
            await conn.execute("update signals set channel_subtype='ui_pers_demo' where id=%s", (sid,))
            ctx = ToolContext(conn, run_id=rid, agent_run_id=arid, sim_time=await sim_now(conn))
            assert (await resume_approved_incident(ctx, iid))["reason"] == "no_approval"
            extra = None
            if other_pending:
                extra = (
                    await (
                        await conn.execute(
                            "insert into human_decisions(sim_run_id,agent_run_id,signal_id,incident_id,requested_sim,reason,agent_proposal,options,recommendation) select sim_run_id,agent_run_id,signal_id,incident_id,requested_sim,reason,agent_proposal,options,recommendation from human_decisions where id=%s returning id",
                            (hid,),
                        )
                    ).fetchone()
                )[0]
            await conn.execute("update human_decisions set decision='accept' where id=%s", (hid,))
            await conn.commit()
            resumed = await resume_after_human(
                conn, human_decision_id=hid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=await sim_now(conn)
            )
            assert resumed and resumed["outcome"] == "deferred"
            status = (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone())[0]
            assert status == ("awaiting_human" if other_pending else "routed")
            if other_pending:
                assert (await resume_approved_incident(ctx, iid))["reason"] == "pending_human_decision"
                await conn.execute("update human_decisions set decision='accept' where id=%s", (extra,))
                assert (await resume_approved_incident(ctx, iid))["resumed"]
            assert not (await resume_approved_incident(ctx, iid))["resumed"]
            await conn.commit()
        await sim.load_state()
        request = Request({"type": "http", "app": app, "headers": []})
        await post_demo_execution(request, DemoExecutionBody(mode="simulation"))
        original = sim.clock.sim_time
        for _ in range(24):
            await cycle(app)
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select status from signals where id=%s", (sid,))).fetchone())[
                0
            ] == "closed"
            assert (
                await (
                    await conn.execute(
                        "select count(*) from notifications where signal_id=%s and template_code='resolved' and status='sent'",
                        (sid,),
                    )
                ).fetchone()
            )[0] == 1
        assert not sim.clock.running and sim.clock.sim_time == original
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
