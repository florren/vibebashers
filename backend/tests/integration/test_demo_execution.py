"""Полный demo-цикл на PostgreSQL: реальные сигналы/инциденты/уведомления, mock LLM."""

from __future__ import annotations

import asyncio

import psycopg
import pytest
from starlette.requests import Request

from app.agent.runner import AgentService
from app.api.demo_execution import DemoExecutionBody, delete_demo_execution, post_demo_execution
from app.config import get_settings
from app.demo.execution import configuration, cycle
from app.main import create_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("outcome", ["on_time", "late", "no_work", "failed", "recovered"])
async def test_demo_full_cycle(seeded, monkeypatch, outcome):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.agent = svc
    app.state.sim = sim
    app.state.llm_chain = svc.chain
    app.state.llm_profile = svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    try:
        result = await post_demo_execution(
            request, DemoExecutionBody(scenario_id="deposit_promo_rate", team_outcome=outcome, emulate_humans=True)
        )
        rid = result["run_id"]
        assert sim.clock.running
        assert result["subject_ref"].startswith("SIG-")
        from app.api.sim import SimControlRequest, post_sim_control

        await post_sim_control(request, SimControlRequest(action="pause"))
        paused_at = sim.clock.sim_time
        await cycle(app)
        assert sim.clock.sim_time == paused_at
        assert not sim.clock.running
        await post_sim_control(request, SimControlRequest(action="resume"))
        assert sim.clock.running
        if outcome == "on_time":
            from app.sim.clock import add_working_days

            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                await conn.execute(
                    "update incidents set complexity='hard',sla_due_sim=%s,report_due_sims=%s where run_id=%s",
                    (
                        add_working_days(sim.clock.sim_time, 10),
                        [add_working_days(sim.clock.sim_time, day) for day in (3, 6, 9)],
                        rid,
                    ),
                )
        for _ in range(24):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                config = await configuration(conn, rid)
            if not config.get("enabled"):
                break
        assert config["status"] == "finished"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            incidents = await (
                await conn.execute(
                    "select status,sla_breached,resolution_summary,outcome_class from incidents where run_id=%s", (rid,)
                )
            ).fetchall()
            assert incidents
            if outcome == "on_time":
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from sim_events where run_id=%s and event_type='sla.report_missing'",
                            (rid,),
                        )
                    ).fetchone()
                )[0] == 0
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from incident_artifacts where run_id=%s and kind='progress_report' and published_sim<=due_sim",
                            (rid,),
                        )
                    ).fetchone()
                )[0] == 3
            success = outcome not in ("no_work", "failed")
            assert all((r[0] == "closed") == success for r in incidents)
            if success:
                assert all(
                    r[2]
                    and r[3]
                    in ({"closed_in_sla", "closed_in_sla_with_gift"} if outcome == "on_time" else {"closed_late"})
                    for r in incidents
                )
            notices = await (
                await conn.execute(
                    "select signal_id,template_code,body from notifications where run_id=%s and recipient_type='client' and template_code in ('resolved','demo_unresolved')",
                    (rid,),
                )
            ).fetchall()
            final_notices = [r for r in notices if r[1] == ("resolved" if success else "demo_unresolved")]
            assert len(final_notices) == 2
            assert len({r[0] for r in final_notices}) == 2
            assert len(notices) == (4 if outcome == "recovered" else 2)
            assert len({(r[0], r[1]) for r in notices}) == len(notices)
            for _, code, body in notices:
                assert not any(
                    word in body.lower() for word in ("стенд", "демонстрац", "маршрут", "эскалац", "внешние действия")
                )
                assert ("устранена" in body) == (code == "resolved")
                assert ("остаётся открытым" in body) == (code == "demo_unresolved")
                if code == "resolved" and outcome in ("late", "recovered"):
                    assert "больше времени" in body
            assert not (
                await (
                    await conn.execute(
                        "select n.id from notifications n join signals s on s.id=n.signal_id where n.run_id=%s and n.template_code in ('resolved','demo_unresolved') and n.channel_code<>s.channel_code",
                        (rid,),
                    )
                ).fetchall()
            )
            before = await (await conn.execute("select count(*) from team_actions where run_id=%s", (rid,))).fetchone()
            await cycle(app)
            after = await (await conn.execute("select count(*) from team_actions where run_id=%s", (rid,))).fetchone()
            assert before == after
            assert (
                (
                    await (
                        await conn.execute(
                            "select count(*) from incident_artifacts where run_id=%s and meta->>'source'='mock'", (rid,)
                        )
                    ).fetchone()
                )[0]
                > 0
                if outcome != "no_work"
                else True
            )
        await delete_demo_execution(request)
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("manual", [False, True])
async def test_demo_operator_and_manual_priority(seeded, monkeypatch, manual):
    from app.agent.graph import process_signal
    from app.api.hitl import HitlDecisionBody, post_hitl_id
    from app.demo.execution import employees, save
    from app.sim import scenarios as sc
    from tests.helpers import new_run, sim_now

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid = await new_run(conn, "demo operator priority", scenario_id="deposit_promo_rate")
            sim.run_id, sim.run_status = rid, "paused"
            scenario = {
                "id": "deposit_promo_rate",
                "inject": [
                    {
                        "channel": "chat",
                        "client": {"segment": "ultra_vip"},
                        "text": "Не могу открыть вклад, приложение зависло с ошибкой 503. Прошу решить проблему.",
                    }
                ],
            }
            signal = (await sc.inject(conn, scenario, rid, sim_time=await sim_now(conn)))[0]
            await save(conn, rid, {"enabled": True, "emulate_humans": True, "status": "running"})
            await conn.commit()
            state = await process_signal(
                conn,
                signal_id=signal["signal_id"],
                chain=mock_chain(),
                profile=MOCK_PROFILE,
                sim_time=sim.clock.sim_time,
            )
            assert state["outcome"] == "awaiting_human"
            hid = (
                await (
                    await conn.execute(
                        "select id from human_decisions where sim_run_id=%s and decision is null order by id desc limit 1",
                        (rid,),
                    )
                ).fetchone()
            )[0]
            await conn.commit()
            if manual:
                await post_hitl_id(
                    Request({"type": "http", "app": app, "headers": []}),
                    hid,
                    HitlDecisionBody(decision="accept", decided_by="operator-review", comment="Решение человека"),
                )
            sim.clock.running = True
            await employees(app, conn, rid, sim.clock.sim_time)
            result = await (
                await conn.execute("select decision,decided_by,use_as_fewshot from human_decisions where id=%s", (hid,))
            ).fetchone()
            assert result[0] == "accept"
            assert result[1] == "operator-review" if manual else result[1].startswith("demo-agent:operator:mock")
            if not manual:
                assert result[2] is False
    finally:
        await app.state.agent.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_twenty_inputs_parallel_run_isolation(seeded):
    from app.agent.graph import process_signal
    from app.sim import scenarios as sc
    from tests.helpers import new_run, sim_now

    inputs = []
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        for scenario in [s for s in sc.load_all() if s["id"].startswith("demo20_")]:
            rid = await new_run(conn, scenario["title_ru"], scenario_id=scenario["id"])
            item = (await sc.inject(conn, scenario, rid, sim_time=await sim_now(conn)))[0]
            inputs.append((rid, item["signal_id"]))
        await conn.commit()
    sem = asyncio.Semaphore(4)

    async def process(rid, sid):
        async with sem, await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            result = await process_signal(conn, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE)
            assert result["outcome"] in ("completed", "deferred", "awaiting_human", "fallback_mock"), (
                sid,
                result.get("errors"),
            )
            rows = await (
                await conn.execute(
                    "select distinct i.run_id from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (sid,),
                )
            ).fetchall()
            assert all(r[0] == rid for r in rows)

    await asyncio.gather(*(process(rid, sid) for rid, sid in inputs))
    assert len(inputs) == 20


@pytest.mark.parametrize("manual", [False, True])
async def test_demo_compliance_manager_and_idempotent_ack(seeded, monkeypatch, manual):
    from app.compliance.session import ComplianceService

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    from app.api.compliance import post_compliance_alerts_id_ack
    from app.demo import execution

    original_employees = execution.employees
    delayed_once = False

    async def delay_manager_once(app, conn, rid, at):
        nonlocal delayed_once
        row = await (
            await conn.execute(
                "select a.id from compliance_alerts a join audio_sessions s on s.id=a.session_id join transcripts t on t.id=s.transcript_id where s.run_id=%s and a.acknowledged_at is null and t.status='done' limit 1",
                (rid,),
            )
        ).fetchone()
        if row and not delayed_once:
            delayed_once = True
            if manual:
                await post_compliance_alerts_id_ack(
                    request, row[0], {"decision": "open_incident", "comment": "Решение руководителя вручную"}
                )
            return False
        return await original_employees(app, conn, rid, at)

    monkeypatch.setattr(execution, "employees", delay_manager_once)
    try:
        state = await post_demo_execution(request, DemoExecutionBody(scenario_id="branch_misselling"))
        rid = state["run_id"]
        for _ in range(300):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                config = await configuration(conn, rid)
            if not config.get("enabled"):
                break
            await asyncio.sleep(0.1)
        assert config["status"] == "finished"
        assert delayed_once
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select a.id,a.decision,a.acknowledged_by,a.incident_id,a.human_decision_id from compliance_alerts a join audio_sessions s on s.id=a.session_id where s.run_id=%s",
                    (rid,),
                )
            ).fetchall()
            assert rows
            notices = await (
                await conn.execute(
                    "select signal_id,body from notifications where run_id=%s and recipient_type='client' and template_code='resolved'",
                    (rid,),
                )
            ).fetchall()
            assert notices and all(n[0] and n[1] for n in notices)
            assert all(r[1] == "open_incident" for r in rows)
            assert all(r[2] == "branch_manager" if manual else r[2].startswith("demo-agent:manager:mock") for r in rows)
            for aid, decision, by, iid, hid in rows:
                service = ComplianceService(
                    conn, run_id=rid, sim_time=sim.clock.sim_time, chain=svc.chain, profile=svc.profile
                )
                repeated = await service.ack_alert(aid, decision="false_positive", by="late-manual")
                assert repeated["deduplicated"] is True
                assert repeated["decision"] == decision
                assert (
                    await (
                        await conn.execute("select acknowledged_by from compliance_alerts where id=%s", (aid,))
                    ).fetchone()
                )[0] == by
                if hid:
                    hd = await (
                        await conn.execute("select decision,use_as_fewshot from human_decisions where id=%s", (hid,))
                    ).fetchone()
                    assert hd[0] == "accept"
                    if not manual:
                        assert hd[1] is False
                if iid:
                    assert (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone())[
                        0
                    ] == "closed"
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_new_catalog_case_runs_without_reseeding_existing_database(seeded, monkeypatch):
    from app.sim import scenarios as sc

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    request = Request({"type": "http", "app": app, "headers": []})
    scenario_id = "demo20_01_branch_queue"
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            clients_before = (await (await conn.execute("select count(*) from clients")).fetchone())[0]
            await conn.execute("delete from scenarios where id=%s", (scenario_id,))
        result = await post_demo_execution(request, DemoExecutionBody(scenario_id=scenario_id))
        assert result["subject_ref"].startswith("SIG-")
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        await delete_demo_execution(request)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute("select title_ru,yaml_source from scenarios where id=%s", (scenario_id,))
            ).fetchone()
            assert row and row[0] == sc.get(scenario_id)["title_ru"] and scenario_id in row[1]
            assert (await (await conn.execute("select count(*) from clients")).fetchone())[0] == clients_before
            await conn.execute("update scenarios set last_result='{}'::jsonb where id=%s", (scenario_id,))
            await sc.ensure_registered(conn, sc.get(scenario_id))
            assert (
                await (await conn.execute("select last_result from scenarios where id=%s", (scenario_id,))).fetchone()
            )[0] == {}
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
