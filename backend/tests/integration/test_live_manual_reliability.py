"""Ручной Journey не ждёт World; архивные часы не ломают карту и метрики."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.agent import policies
from app.agent.nodes import _policy_context
from app.agent.runner import AgentService
from app.agent.tools import router_tools, write
from app.agent.tools.base import ActFrame, ToolContext
from app.agent.tools.read import count_same_cause, search_similar_signals
from app.demo.execution import public_cycle
from app.main import create_app
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now
from tests.integration.test_journey_execution_scope import bank_snapshot, message, send, setup


@pytest.mark.parametrize("wake", ["ingest", "notification", "recovery"])
async def test_manual_journey_runs_with_saturated_world_queue(seeded, monkeypatch, wake):
    app, sim, request = await setup(monkeypatch, seeded)
    service = None
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
            cid = (await (await conn.execute("select id from clients where segment_code='mass' limit 1")).fetchone())[0]
        body = message("priority-root", options={"emulate_humans": False, "auto_advance": True})
        body["client"] = {"client_id": cid}
        service = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
        service.enabled = wake == "ingest"
        for _ in range(4):
            await service.sem.acquire()
        signal = (await send(request, body))["signal_id"]
        service.enabled = True
        if wake == "notification":
            await service._notification(
                SimpleNamespace(
                    channel="sim_events",
                    payload=json.dumps(
                        {
                            "event_type": "signal.received",
                            "payload": {"signal_id": signal},
                        }
                    ),
                )
            )
        elif wake == "recovery":
            await public_cycle(app)  # Также восстанавливает потерянный NOTIFY после restart.
        assert service._inflight
        await asyncio.wait_for(asyncio.gather(*list(service._inflight)), 10)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select outcome from agent_runs where signal_id=%s and kind='agent'",
                    (signal,),
                )
            ).fetchone()
            assert row and row[0] in ("completed", "deferred")
            assert await bank_snapshot(conn) == before
        assert service.sem.locked() and sim.clock.running is False
    finally:
        if service:
            await service.stop()
        await sim.shutdown()


def test_all_map_metrics_accept_archived_and_private_clocks_but_reject_world_future(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    with psycopg.connect(dsn(seeded)) as conn:
        now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
        archived = conn.execute(
            "insert into sim_runs(kind,label,seed,status,started_sim,finished_sim) "
            "values('free','old bank',42,'archived',%s,%s) returning id",
            (now + dt.timedelta(days=4), now + dt.timedelta(days=5)),
        ).fetchone()[0]
        case = conn.execute(
            "insert into sim_runs(kind,label,seed,status,started_sim,settings_snapshot) "
            "values('live','private clock',42,'paused',%s,'{\"created_by\":\"journey_demo\"}') returning id",
            (now + dt.timedelta(days=2),),
        ).fetchone()[0]
    with TestClient(create_app()) as client:
        for endpoint in ("/api/map/heat", "/api/map/zones", "/api/metrics/overview", "/api/metrics/cx-index"):
            response = client.get(endpoint, params={"run_id": "all"})
            assert response.status_code == 200, response.text[:300]
        with psycopg.connect(dsn(seeded)) as conn:
            # Неизвестный обычный run с будущим временем не становится допустимым.
            conn.execute("update sim_runs set status='paused' where id=%s", (archived,))
        for endpoint in ("/api/metrics/overview", "/api/metrics/cx-index"):
            response = client.get(endpoint, params={"run_id": "all"})
            assert response.status_code == 409 and "temporal_context_conflict" in response.text
        with psycopg.connect(dsn(seeded)) as conn:
            assert conn.execute("select sim_time from sim_state where id=1").fetchone() == (now,)
            assert conn.execute("select status from sim_runs where id=%s", (case,)).fetchone() == ("paused",)


async def test_autonomy_counts_real_deferred_decisions_without_pending_or_human_cases(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "autonomy decisions")
        at = await sim_now(conn)
        signal = (await (await conn.execute("select id from signals order by id limit 1")).fetchone())[0]
        await conn.execute("update signals set run_id=%s,received_sim=%s where id=%s", (rid, at, signal))
        for outcome, needed in (
            [("completed", False)] * 3
            + [("deferred", False)] * 4
            + [("awaiting_human", True)] * 2
            + [("failed", False)]
            + [(None, False)] * 2
        ):
            await conn.execute(
                "insert into agent_runs(kind,sim_run_id,signal_id,started_sim,outcome,needed_human,prompt_version,finished_at) "
                "values('agent',%s,%s,%s,%s,%s,'autonomy regression',case when %s='completed' then now() end)",
                (rid, signal, at, outcome, needed, outcome),
            )
        await conn.commit()
    with TestClient(create_app()) as client:
        dashboard = client.get("/api/metrics/dashboard", params={"run_id": rid}).json()
        overview = client.get("/api/metrics/overview", params={"run_id": rid}).json()
        assert dashboard["agent_runs"] == 12
        assert dashboard["autonomous_share"] == overview["kpi"]["autonomous_share"] == 70
        assert dashboard["hitl_share"] == 20


async def test_escalation_notice_preserves_autonomy_and_real_approval_remains_blocking(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "escalation notice")
        at = await sim_now(conn)
        sid = (await (await conn.execute("select id from signals order by id limit 1")).fetchone())[0]
        await conn.execute("update signals set run_id=%s where id=%s", (rid, sid))
        aid = (
            await (
                await conn.execute(
                    "insert into agent_runs(kind,sim_run_id,signal_id,started_sim,prompt_version) values('agent',%s,%s,%s,'notice regression') returning id",
                    (rid, sid, at),
                )
            ).fetchone()
        )[0]
        ctx = ToolContext(conn, run_id=rid, agent_run_id=aid, sim_time=at)
        incident = await write.create_incident(
            ctx,
            sid,
            None,
            {
                "incident_type": "tech_fault",
                "product": "debit_card",
                "system": "processing",
                "criticality": "high",
                "title_ru": "Сбой обработки",
                "team": "team_processing",
                "priority": 1,
                "sla": {"due_sim": at + dt.timedelta(days=1), "take_due_sim": at + dt.timedelta(hours=1)},
            },
        )
        iid = incident["incident_id"]
        assert incident["status"] == "routed"
        ctx.act_frame = ActFrame(sid, None, iid, None)
        notice = await router_tools.escalate_to_manager(ctx, "critical_severity", "critical")
        assert notice["hitl_item_id"]
        assert (await (await conn.execute("select needed_human from agent_runs where id=%s", (aid,))).fetchone()) == (
            False,
        )
        approval = await write.request_human_decision(
            ctx,
            sid,
            iid,
            "legal_regulatory",
            {},
            policies.human_options("legal_regulatory"),
            "Требуется подтверждение",
        )
        assert approval["human_decision_id"] != notice["hitl_item_id"]
        assert (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone()) == (
            "escalated",
        )
        assert (await (await conn.execute("select needed_human from agent_runs where id=%s", (aid,))).fetchone()) == (
            True,
        )
        await router_tools.escalate_to_manager(ctx, "critical_severity", "critical")
        assert (await (await conn.execute("select needed_human from agent_runs where id=%s", (aid,))).fetchone()) == (
            True,
        )
        await conn.rollback()


async def test_repeat_history_is_scoped_and_compares_cause_not_broad_signal_type(seeded):
    target = {
        "signal_type": "tech_fault",
        "confidence": 0.95,
        "product": "debit_card",
        "system": "processing",
        "error_code": "PROC-DOUBLE-DEBIT",
    }
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "same cause history")
        at = await sim_now(conn)
        cid = (
            await (
                await conn.execute(
                    "insert into clients(display_name,segment_code,psychotype_code,region_code,city_id,clv_estimate_rub) "
                    "select 'Клиент регрессии повторов',segment_code,psychotype_code,region_code,city_id,clv_estimate_rub "
                    "from clients where segment_code='mass' limit 1 returning id"
                )
            ).fetchone()
        )[0]
        baseline_id = (
            await (await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")).fetchone()
        )[0]
        foreign = (
            await (
                await conn.execute(
                    "insert into sim_runs(kind,label,seed,status,started_sim) values('live','other private case',42,'paused',%s) returning id",
                    (at,),
                )
            ).fetchone()
        )[0]
        entries = [
            (rid, target),
            (baseline_id, target),
            (rid, {**target, "error_code": "APP-LOGIN-FAIL"}),
            (rid, {**target, "error_code": "DEP-TIMEOUT-503"}),
        ] + [(foreign, target)] * 4
        for run, classification in entries:
            await conn.execute(
                "insert into signals(run_id,client_id,channel_code,text,received_sim,origin,status,classification) "
                "values(%s,%s,'chat','Учебное обращение для проверки повторов',%s,'jury','classified',%s)",
                (run, cid, at - dt.timedelta(minutes=1), Jsonb(classification)),
            )
        ctx = ToolContext(conn, run_id=rid, agent_run_id=0, sim_time=at)
        history = await search_similar_signals(ctx, "Другая проблема", cid)
        assert history["client_history"]["signals_14d"] == 4
        current_signal = (
            await (
                await conn.execute(
                    "insert into signals(run_id,client_id,channel_code,text,received_sim,origin,status,classification) "
                    "values(%s,%s,'chat','Текущая жалоба',%s,'jury','classified',%s) returning id",
                    (rid, cid, at, Jsonb(target)),
                )
            ).fetchone()
        )[0]
        # COUNT не ограничен20 preview-строками: настоящие повторы могут быть старше новых иных сбоев.
        for _ in range(30):
            await conn.execute(
                "insert into signals(run_id,client_id,channel_code,text,received_sim,origin,status,classification) "
                "values(%s,%s,'chat','Другой сбой',%s,'jury','classified',%s)",
                (rid, cid, at, Jsonb({**target, "error_code": "APP-LOGIN-FAIL"})),
            )
        assert await count_same_cause(ctx, cid, current_signal, target, None) == 2
        state = {
            "signal": {"id": current_signal},
            "client": {"client_id": cid},
            "normalization": {},
            "classification": target,
            "context": {"client_history": history["client_history"]},
        }
        context = await _policy_context(state, SimpleNamespace(ctx=ctx))  # type: ignore[arg-type]
        assert context.repeat_count == 3 and policies.needs_human(target, context) == "repeat_3plus"
        different = {**target, "error_code": "PROC-OTHER-ERROR"}
        state["classification"] = different
        context = await _policy_context(state, SimpleNamespace(ctx=ctx))  # type: ignore[arg-type]
        assert context.repeat_count == 1 and policies.needs_human(different, context) is None
        summary = {
            "signal_type": "service_quality",
            "product": "debit_card",
            "problem_summary": {"problem": "Ошибка оплаты"},
        }
        for product in ("debit_card", "debit_card", "deposit"):
            await conn.execute(
                "insert into signals(run_id,client_id,channel_code,text,received_sim,origin,status,classification) "
                "values(%s,%s,'chat','История проблемы',%s,'jury','classified',%s)",
                (
                    rid,
                    cid,
                    at,
                    Jsonb({**summary, "product": product, "problem_summary": {"problem": "  ОШИБКА   оплаты "}}),
                ),
            )
        assert await count_same_cause(ctx, cid, current_signal, summary, None) == 2
        assert await count_same_cause(ctx, cid, current_signal, {"signal_type": "tech_fault"}, None) == 0
        await conn.rollback()
