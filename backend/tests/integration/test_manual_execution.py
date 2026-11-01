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
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, run_agent_on


@pytest.mark.parametrize("faulted,humans", [(False, True), (True, True), (True, False)])
async def test_manual_employee_and_final_with_bank_paused_after_error(seeded, monkeypatch, faulted, humans):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    try:
        await post_demo_execution(
            request, DemoExecutionBody(mode="simulation", emulate_humans=humans, auto_advance=True)
        )
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
            if not humans:
                assert row[0] is None
                assert (
                    await (
                        await conn.execute("select status from signals where id=%s", (submitted["signal_id"],))
                    ).fetchone()
                )[0] == "awaiting_human"
                assert not sim.clock.running and sim.clock.sim_time == original
                return
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


@pytest.mark.parametrize("outcome", ["on_time", "late", "no_work", "failed", "recovered"])
async def test_manual_team_outcomes_without_global_sla_tick(seeded, monkeypatch, outcome):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    body = DemoExecutionBody(mode="simulation", team_outcome=outcome, emulate_humans=True, auto_advance=True)
    try:
        await post_demo_execution(request, body)
        rid = sim.run_id
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
            cfg = await configuration(conn, rid)
            cfg.update(enabled=False, status="error", error="ToolError")
            await save(conn, rid, cfg)
        saved = await post_demo_execution(request, body)
        assert saved["run_id"] == rid and saved["configuration"]["error"] is None
        assert saved["configuration"]["status"] == "paused"
        result = await post_signals(
            request,
            SignalCreate(
                channel_code="chat",
                client_id=cid,
                text="Не открывается история операций по карте в мобильном приложении: экран зависает и появляется ошибка",
            ),
        )
        before = sim.clock.sim_time
        for _ in range(36):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        success = outcome in ("on_time", "late", "recovered")
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            iid, status = await (
                await conn.execute(
                    "select i.id,i.status from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (result["signal_id"],),
                )
            ).fetchone()
            assert status == ("closed" if success else "escalated")
            notices = await (
                await conn.execute(
                    "select template_code,body from notifications where signal_id=%s and recipient_type='client' "
                    "and template_code in ('resolved','demo_unresolved') and status='sent' order by id",
                    (result["signal_id"],),
                )
            ).fetchall()
            assert len(notices) == (2 if outcome == "recovered" else 1)
            if outcome == "recovered":
                assert notices[0][0] == "demo_unresolved" and "вернёмся к вам" in notices[0][1]
            template, text = notices[-1]
            assert template == ("resolved" if success else "demo_unresolved")
            if not success:
                assert "больше времени" in text and "вернёмся к вам" in text and "устранена" not in text
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from tasks where incident_id=%s and kind='gift' and status='done' "
                            "and payload ? 'issued'",
                            (iid,),
                        )
                    ).fetchone()
                )[0] == 0
            if outcome in ("failed", "recovered"):
                transitions = await (
                    await conn.execute(
                        "select from_status,to_status from incident_status_history where incident_id=%s order by id",
                        (iid,),
                    )
                ).fetchall()
                assert ("fix_proposed", "in_progress") in transitions
                assert ("in_progress", "escalated") in transitions
            agent = await (
                await conn.execute("select outcome from agent_runs where id=%s", (result["agent_run_id"],))
            ).fetchone()
            assert agent[0] == ("completed" if success else "deferred")
        await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute(
                        "select count(*) from notifications where signal_id=%s and template_code=%s",
                        (result["signal_id"], template),
                    )
                ).fetchone()
            )[0] == 1
        assert not sim.clock.running and sim.clock.sim_time == before
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("already_accepted", [False, True])
async def test_related_bulk_review_is_in_manual_chain_but_unrelated_review_is_not(
    seeded, monkeypatch, already_accepted
):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    try:
        await post_demo_execution(request, DemoExecutionBody(mode="simulation", emulate_humans=True))
        rid = sim.run_id
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await conn.execute(
                "insert into settings(key,value) values ('policies','{\"confidence_threshold\":0.99}') on conflict(key) do update set value=settings.value || excluded.value"
            )
            bulk, bstate = await run_agent_on(
                conn,
                "В мобильном приложении не открывается вклад, ошибка 503",
                client_id=None,
                run_id=rid,
                origin="sim",
            )
            unrelated, ustate = await run_agent_on(
                conn,
                "Не загружается PDF выписка по кредитной карте в приложении",
                client_id=None,
                run_id=rid,
                origin="sim",
            )
            assert bstate["outcome"] == "awaiting_human" and ustate["outcome"] == "awaiting_human"
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1")
                ).fetchone()
            )[0]
            cfg = await configuration(conn, rid)
            cfg.update(enabled=False, status="error", error="ToolError")
            await save(conn, rid, cfg)
        result = await post_signals(
            request,
            SignalCreate(
                channel_code="chat", client_id=cid, text="В мобильном приложении не открывается вклад, ошибка 503"
            ),
        )
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            # Явная общая связь: anonymous mock не обязан распознавать тот же инцидент.
            iid = (
                await (
                    await conn.execute("select incident_id from incident_signals where signal_id=%s", (bulk,))
                ).fetchone()
            )[0]
            await conn.execute(
                "insert into incident_signals(incident_id,signal_id,linked_sim) values (%s,%s,%s) on conflict do nothing",
                (iid, result["signal_id"], sim.clock.sim_time),
            )
            await conn.execute(
                'update human_decisions set agent_proposal=agent_proposal || \'{"kind":"escalation"}\'::jsonb where signal_id=%s',
                (bulk,),
            )
            if already_accepted:
                await conn.execute(
                    "update human_decisions set decision='accept',decided_by='operator',decided_at=now() where signal_id=%s",
                    (bulk,),
                )
        before = sim.clock.sim_time
        for _ in range(40):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            ids = await (
                await conn.execute(
                    "select signal_id from incident_signals where incident_id=%s and signal_id=any(%s)",
                    (iid, [bulk, result["signal_id"]]),
                )
            ).fetchall()
            assert len(ids) == 2
            assert (
                await (
                    await conn.execute("select decision from human_decisions where signal_id=%s", (bulk,))
                ).fetchone()
            )[0] == "accept"
            assert (
                await (
                    await conn.execute("select decision from human_decisions where signal_id=%s", (unrelated,))
                ).fetchone()
            )[0] is None
            assert (
                await (
                    await conn.execute(
                        "select outcome from agent_runs where signal_id=%s and kind='agent'", (result["signal_id"],)
                    )
                ).fetchone()
            )[0] == "completed"
        assert not sim.clock.running and sim.clock.sim_time == before
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


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
