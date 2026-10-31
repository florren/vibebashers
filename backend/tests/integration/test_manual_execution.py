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
from app.demo.settings import configuration, save
from app.main import create_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain


@pytest.mark.parametrize("faulted", [False, True])
async def test_manual_employee_and_final_with_bank_paused_after_error(seeded, monkeypatch, faulted):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    try:
        await post_demo_execution(request, DemoExecutionBody(mode="simulation", emulate_humans=True, auto_advance=True))
        rid = sim.run_id
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1")
                ).fetchone()
            )[0]
            if faulted:
                config = await configuration(conn, rid)
                config.update(enabled=False, status="error", error="ToolError")
                await save(conn, rid, config)
        submitted = await post_signals(
            request,
            SignalCreate(
                channel_code="chat",
                client_id=cid,
                text="В мобильном приложении не открывается вклад: ошибка 503 после подтверждения. Списаний не было.",
            ),
        )
        original = sim.clock.sim_time
        for _ in range(32):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select decision,decided_by,use_as_fewshot from human_decisions where signal_id=%s order by id limit 1",
                    (submitted["signal_id"],),
                )
            ).fetchone()
            assert row[0] == "accept" and row[1].startswith("demo-agent:operator:") and not row[2]
            assert (
                await (
                    await conn.execute("select status from signals where id=%s", (submitted["signal_id"],))
                ).fetchone()
            )[0] == "closed"
            final = await (
                await conn.execute(
                    "select body from notifications where signal_id=%s and template_code='resolved' and status='sent'",
                    (submitted["signal_id"],),
                )
            ).fetchall()
            assert len(final) == 1 and "устранена" in final[0][0] and "стенд" not in final[0][0]
            assert (
                await (
                    await conn.execute(
                        "select outcome from agent_runs where signal_id=%s and kind='agent'", (submitted["signal_id"],)
                    )
                ).fetchone()
            )[0] == "completed"
            config = await configuration(conn, rid)
            if faulted:
                assert config["error"] == "ToolError" and not config["enabled"]
        assert not sim.clock.running and sim.clock.sim_time == original
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


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
