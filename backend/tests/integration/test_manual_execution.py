"""Ручные сигналы вне симуляции: история клиента, общий инцидент, итог без ожидания дней."""

import asyncio

import psycopg
import pytest
from starlette.requests import Request

from app.agent.runner import AgentService
from app.agent.tools.base import ToolContext
from app.agent.tools.read import search_similar_signals
from app.api.demo_execution import DemoExecutionBody, post_demo_execution
from app.api.signals import SignalCreate, post_signals
from app.config import get_settings
from app.demo.execution import cycle
from app.main import create_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("fast", [False, True, None])
async def test_manual_paused_history_and_final_reply(seeded, monkeypatch, fast):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.agent, app.state.sim = svc, sim
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    try:
        if fast is not None:
            await post_demo_execution(request, DemoExecutionBody(mode="simulation", auto_advance=fast))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
        ids = []
        for text in (
            "Не могу открыть вклад в мобильном приложении: после подтверждения ошибка 503",
            "Повторно: ошибка 503 при открытии вклада в мобильном приложении",
        ):
            submitted = await post_signals(request, SignalCreate(channel_code="chat", client_id=cid, text=text))
            ids.append(submitted["signal_id"])
        assert ids[0] != ids[1]
        rid = sim.run_id
        original_time = sim.clock.sim_time
        for _ in range(32):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        assert not sim.clock.running
        assert sim.clock.sim_time == original_time
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            hist = await search_similar_signals(
                ToolContext(conn, run_id=rid, agent_run_id=0, sim_time=original_time), text="вклад", client_id=cid
            )
            assert hist["client_history"]["signals_14d"] >= 2
            links = await (
                await conn.execute("select distinct incident_id from incident_signals where signal_id=any(%s)", (ids,))
            ).fetchall()
            assert len(links) == 1
            notices = await (
                await conn.execute(
                    "select signal_id from notifications where run_id=%s and signal_id=any(%s) and template_code='resolved'",
                    (rid, ids),
                )
            ).fetchall()
            assert sorted(r[0] for r in notices) == (sorted(ids) if fast is not False else [])
            assert (
                await (
                    await conn.execute("select count(*) from signals where run_id=%s and origin<>'jury'", (rid,))
                ).fetchone()
            )[0] == 0
            before = (
                await (await conn.execute("select count(*) from team_actions where run_id=%s", (rid,))).fetchone()
            )[0]
        await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select count(*) from team_actions where run_id=%s", (rid,))).fetchone())[
                0
            ] == before
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
