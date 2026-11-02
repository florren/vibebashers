"""T-235: полная матрица через actual ASGI/PG и красный тест при попытке записи."""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager

import httpx
import psycopg
import pytest
from app.api import public, trace
from app.ingest.normalizer import create_signal, from_api_signal, from_landing
from app.llm.failover import ProviderChain
from app.main import create_app
from app.sim import scenarios
from app.trace import store
from fastapi import HTTPException
from psycopg.rows import dict_row

from scripts import read_model_check, scenario_check
from tests.helpers import dsn, new_run, sim_now

pytestmark = pytest.mark.integration


async def test_actual_get_matrix_and_write_detector(seeded, monkeypatch):
    # Явно синтетический граф — это fixture поиска, не фиктивный completed LLM run.
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "synthetic search acceptance")
        now = await sim_now(conn)
        cid = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        accepted = await create_signal(
            conn,
            from_api_signal(
                {"channel_code": "chat", "client_id": cid, "text": "Синтетическая проверка поиска"}, origin="jury"
            ),
            source_code="api",
            run_id=rid,
            sim_time=now,
            emit_event=False,
        )
        sid = accepted["signal_id"]
        await public._ensure_source(conn, "landing", "landing")
        await create_signal(
            conn,
            from_landing(
                contact={"email": "synthetic@example.com"},
                text="Синтетическое публичное обращение",
                tracking_token="synthetic_tracking_capability_235",
            ),
            source_code="landing",
            run_id=rid,
            sim_time=now,
            emit_event=False,
        )
        await scenarios.inject_operation(
            conn, rid, cid, {"amount_rub": 100, "fee_amount": 4.5, "error_code": "PROC-QR-FEE-CHARGED"}, now
        )
        ar = (
            await (
                await conn.execute(
                    "insert into agent_runs(sim_run_id,signal_id,prompt_version,outcome,started_sim) values(%s,%s,'synthetic-search-fixture','deferred',%s) returning id",
                    (rid, sid, now),
                )
            ).fetchone()
        )[0]
        iid = (
            await (
                await conn.execute(
                    "insert into incidents(run_id,title,incident_type,product_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,primary_client_id,agent_run_id) values(%s,'Синтетический инцидент','tariff_terms','debit_card','team_cx','easy','high',1,'escalated','scenario',%s,%s,%s,%s,%s) returning id",
                    (rid, now, now, now, cid, ar),
                )
            ).fetchone()
        )[0]
        await conn.execute(
            "insert into incident_signals(incident_id,signal_id,link_type,linked_sim) values(%s,%s,'primary',%s)",
            (iid, sid, now),
        )
        for index in range(120):
            message = from_api_signal(
                {
                    "channel_code": "chat",
                    "client_id": cid,
                    "text": f"Синтетическое повторное обращение {index}",
                    "external_id": f"t235-fanout-{index}",
                },
                origin="jury",
            )
            child = await create_signal(
                conn, message, source_code="api", run_id=rid, sim_time=now + dt.timedelta(minutes=1), emit_event=False
            )
            await conn.execute(
                "insert into incident_signals(incident_id,signal_id,linked_sim) values(%s,%s,%s)",
                (iid, child["signal_id"], now + dt.timedelta(minutes=1)),
            )
        task = (
            await (
                await conn.execute(
                    "insert into tasks(run_id,kind,incident_id,created_sim) values(%s,'manual_review',%s,%s) returning id",
                    (rid, iid, now),
                )
            ).fetchone()
        )[0]
        hid = (
            await (
                await conn.execute(
                    "insert into human_decisions(sim_run_id,agent_run_id,signal_id,incident_id,task_id,requested_sim,reason,agent_proposal,options) values(%s,%s,%s,%s,%s,%s,'synthetic search','{}','[]') returning id",
                    (rid, ar, sid, iid, task, now),
                )
            ).fetchone()
        )[0]
        await conn.execute(
            "insert into escalations(run_id,signal_id,incident_id,human_decision_id,reason,severity,to_role,created_by,created_sim) values(%s,%s,%s,%s,'synthetic search','high','cx_lead','agent',%s)",
            (rid, sid, iid, hid, now),
        )
        emp, branch = await (await conn.execute("select id,branch_id from employees order by id limit 1")).fetchone()
        audio = (
            await (
                await conn.execute(
                    "insert into audio_sessions(run_id,branch_id,employee_id,source,stt_provider,diarization_mode,started_sim) values(%s,%s,%s,'transcript','none','manual',%s) returning id",
                    (rid, branch, emp, now),
                )
            ).fetchone()
        )[0]
        own_alert = (
            await (
                await conn.execute("insert into compliance_alerts(session_id) values(%s) returning id", (audio,))
            ).fetchone()
        )[0]
        other_run = (
            await (
                await conn.execute(
                    "insert into sim_runs(kind,label,seed,started_sim) values('scenario','foreign search fixture',42,%s) returning id",
                    (now,),
                )
            ).fetchone()
        )[0]
        other_audio = (
            await (
                await conn.execute(
                    "insert into audio_sessions(run_id,branch_id,employee_id,source,stt_provider,diarization_mode,started_sim) values(%s,%s,%s,'transcript','none','manual',%s) returning id",
                    (other_run, branch, emp, now),
                )
            ).fetchone()
        )[0]
        other_alert = (
            await (
                await conn.execute("insert into compliance_alerts(session_id) values(%s) returning id", (other_audio,))
            ).fetchone()
        )[0]
        await conn.execute(
            "insert into transcripts(run_id,kind,source,format,turns,received_sim,audio_session_id,branch_id,employee_id,signal_id) values(%s,'branch_retail','api','json','[]',%s,%s,%s,%s,%s)",
            (rid, now, audio, branch, emp, sid),
        )
        await conn.execute(
            "insert into external_posts(run_id,platform,author_nick,text,posted_sim,signal_id) values(%s,'review_portal','synthetic_case','Синтетический пост',%s,%s)",
            (rid, now, sid),
        )
        await conn.execute(
            "insert into notifications(run_id,signal_id,recipient_type,channel_code,body) values(%s,%s,'cx','internal','Синтетическое уведомление')",
            (rid, sid),
        )
        await conn.execute(
            "insert into followups(sim_run_id,agent_run_id,signal_id,wake_sim,reason) values(%s,%s,%s,%s,'awaiting_client')",
            (rid, ar, sid, now),
        )
        await conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as reader:
        await reader.execute("SET TRANSACTION READ ONLY")
        assert (await store.resolve(reader, "alert", str(own_alert), str(rid)))["scope_id"] == rid
        with pytest.raises(HTTPException) as rejected:
            await store.resolve(reader, "alert", str(other_alert), str(rid))
        assert rejected.value.status_code == 404
    llm_calls = []

    async def forbidden(*args, **kwargs):
        llm_calls.append(True)
        raise AssertionError("Read model must not call LLM")

    monkeypatch.setattr(ProviderChain, "complete_structured", forbidden)

    @asynccontextmanager
    async def connection():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as conn:
            yield conn

    monkeypatch.setattr(store, "db", connection)
    app = create_app()
    for route in app.routes:
        if getattr(route, "path", "").startswith(("/api/search", "/api/trace", "/api/journey")):
            assert route.methods <= {"GET", "HEAD"}
    client_type = httpx.AsyncClient
    methods = []

    async def record(request):
        methods.append(request.method)

    monkeypatch.setattr(
        read_model_check.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            **kwargs, transport=httpx.ASGITransport(app=app), event_hooks={"request": [record]}
        ),
    )
    scenario = scenarios.get("search_and_trace")
    assert await scenario_check.run_one("http://test", dsn(seeded), scenario, 0)
    assert len(methods) == 47  # 17prefixes +9formats +17traces +4contexts, без write endpoints.
    assert set(methods) == {"GET"}
    assert llm_calls == []
    original = trace.assemble

    async def illegal_write(conn, *args, **kwargs):
        await conn.execute("insert into settings(key,value) values('forbidden-read-model-write','true')")
        return await original(conn, *args, **kwargs)

    monkeypatch.setattr(trace, "assemble", illegal_write)
    case = read_model_check.SearchCase("prefix:SIG", "SIG-000001", "signal", "SIG-000001")
    async with client_type(base_url="http://test", transport=httpx.ASGITransport(app=app)) as http:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await read_model_check.check_trace(http, case)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        assert (
            await (await conn.execute("select 1 from settings where key='forbidden-read-model-write'")).fetchone()
            is None
        )
