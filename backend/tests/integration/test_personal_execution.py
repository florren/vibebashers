"""Публичный origin проходит ту же цепочку при паузе, включая опоздание и раздельные проблемы."""

import asyncio
import datetime as dt
import uuid
from functools import partial

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.agent.runner import AgentService
from app.api.demo_execution import DemoExecutionBody, post_demo_execution
from app.config import get_settings
from app.demo.execution import cycle, public_cycle
from app.main import create_app
from app.public_chat import create_public_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("offset,empty_pointer", [(0, False), (1, False), (2, False), (3, False), (0, True)])
async def test_personal_full_chain_without_bank_clock(seeded, monkeypatch, offset, empty_pointer):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    request = Request({"type": "http", "app": app, "headers": []})
    client = TestClient(create_public_app())
    try:
        if empty_pointer:
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                await conn.execute("update sim_state set current_run_id=null where id=1")
        if not empty_pointer:
            await post_demo_execution(request, DemoExecutionBody(mode="simulation", team_outcome="failed"))
        from app.demo.public import OUTCOMES, public_context, recover_public_cases
        from app.demo.settings import configuration, save

        monkeypatch.setattr(
            "app.demo.public.recover_public_cases", partial(recover_public_cases, now=dt.datetime.now(dt.UTC))
        )
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            public_rid, _ = await public_context(conn)
            cfg = await configuration(conn, public_rid)
            cfg["outcome_cursor"] = offset
            await save(conn, public_rid, cfg)
            if sim.run_id:
                bank_cfg = await configuration(conn, sim.run_id)
                bank_cfg.update(enabled=False, auto_advance=False, emulate_humans=False, status="stopped")
                await save(conn, sim.run_id, bank_cfg)
        sim.run_status = "stopped"
        expected = [OUTCOMES[offset % len(OUTCOMES)], OUTCOMES[(offset + 1) % len(OUTCOMES)]]
        boot = client.get("/api/personal/session").json()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await conn.execute("update personal_chat_sessions set created_at=now()-interval '3 seconds'")
        payload = {
            "request_id": str(uuid.uuid4()),
            "form_token": boot["form_token"],
            "display_name": "Демо клиент",
            "voice": bool(offset),
            "product_code": "deposit",
            "text": "Не могу открыть вклад в мобильном приложении: ошибка 503 после подтверждения, списаний не было.",
        }
        accepted = client.post("/api/personal/messages", json=payload)
        assert accepted.status_code == 202, accepted.text
        assert client.post("/api/personal/messages", json=payload).json() == accepted.json()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            first = await (
                await conn.execute("select id,run_id from signals where public_id=%s", (accepted.json()["public_id"],))
            ).fetchone()
            await conn.execute("update personal_chat_sessions set last_message_at=now()-interval '3 seconds'")
        second = client.post(
            "/api/personal/messages",
            json={
                **payload,
                "request_id": str(uuid.uuid4()),
                "product_code": "credit_card",
                "text": "Не открывается PDF выписка по кредитной карте в приложении, ошибка загрузки документа.",
            },
        )
        assert second.status_code == 202, second.text
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            sid = (
                await (
                    await conn.execute("select id from signals where public_id=%s", (second.json()["public_id"],))
                ).fetchone()
            )[0]
        assert sid != first[0]
        bank_run = sim.run_id
        original = sim.clock.sim_time
        await asyncio.gather(svc.submit(first[0], interactive=True), svc.submit(sid, interactive=True))
        signal_ids = [first[0], sid]
        if offset == 0 and not empty_pointer:
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                await conn.execute("update personal_chat_sessions set last_message_at=now()-interval '3 seconds'")
            repeat = client.post("/api/personal/messages", json={**payload, "request_id": str(uuid.uuid4())})
            assert repeat.status_code == 202, repeat.text
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                repeat_id = (
                    await (
                        await conn.execute("select id from signals where public_id=%s", (repeat.json()["public_id"],))
                    ).fetchone()
                )[0]
            await svc.submit(repeat_id, interactive=True)
            signal_ids.append(repeat_id)
            expected.append(expected[0])
        async with sim._lock:
            # Даже длительное исполнение Journey не блокирует отдельную публичную очередь.
            await asyncio.wait_for(public_cycle(app), timeout=5)
        for _ in range(32):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await public_cycle(app)
            await cycle(app)
        assert sim.run_id == bank_run and first[1] != bank_run
        assert not sim.clock.running and sim.clock.sim_time == original
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select s.id,s.status,i.id,i.product_code,i.status,i.sla_breached from signals s join incident_signals x on x.signal_id=s.id join incidents i on i.id=x.incident_id where s.id=any(%s) order by s.id",
                    (signal_ids,),
                )
            ).fetchall()
            assert len(rows) == len(signal_ids) and len({r[2] for r in rows}) == 2
            if len(rows) == 3:
                assert rows[0][2] == rows[2][2]
            cfg = await configuration(conn, public_rid)
            for row in rows:
                outcome = cfg["incident_outcomes"][str(row[2])]
                success = outcome in ("on_time", "late", "recovered")
                assert row[4] == ("closed" if success else "escalated")
                assert row[1] == ("closed" if success else "deferred")
                if success:
                    assert row[5] == (outcome != "on_time")
            cfg = await configuration(conn, public_rid)
            assert cfg["outcome_cursor"] == offset + 2
            assert list(cfg["incident_outcomes"].values()) == expected[:2]
            finals = await (
                await conn.execute(
                    "select signal_id,body from notifications where signal_id=any(%s) and template_code in ('resolved','demo_unresolved') and status='sent'",
                    (signal_ids,),
                )
            ).fetchall()
            assert len(finals) == len(signal_ids) + expected.count("recovered")
        history = client.get("/api/personal/messages").json()
        assert len(history["messages"]) == len(signal_ids)
        assert all(any(n[1] == a["text"] for a in history["answers"]) for n in finals)
        outsider = TestClient(create_public_app())
        outsider.get("/api/personal/session")
        assert outsider.get("/api/personal/messages").json() == {"messages": [], "answers": []}
        assert client.get("/api/settings").status_code == 404
        await cycle(app)
        assert len(client.get("/api/personal/messages").json()["answers"]) == len(history["answers"])
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("initial", ["no_work", "failed"])
@pytest.mark.parametrize("trigger", ["timer", "repeat"])
async def test_public_recovery_is_a_second_scenario_for_same_incident(seeded, monkeypatch, initial, trigger):
    from app.demo.public import OUTCOMES, public_context, recover_public_cases
    from app.demo.settings import configuration, save

    monkeypatch.setattr(
        "app.demo.public.recover_public_cases", partial(recover_public_cases, now=dt.datetime.now(dt.UTC))
    )
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    client = TestClient(create_public_app())
    try:
        before = sim.clock.sim_time
        bank_run = sim.run_id
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid, _ = await public_context(conn)
            config = await configuration(conn, rid)
            config["outcome_cursor"] = OUTCOMES.index(initial)
            await save(conn, rid, config)
        boot = client.get("/api/personal/session").json()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await conn.execute("update personal_chat_sessions set created_at=now()-interval '3 seconds'")
        payload = {
            "request_id": str(uuid.uuid4()),
            "form_token": boot["form_token"],
            "product_code": "deposit",
            "text": "Не могу открыть вклад в мобильном приложении: ошибка 503 после подтверждения. Списаний не было.",
        }
        accepted = client.post("/api/personal/messages", json=payload)
        assert accepted.status_code == 202
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            sid = (
                await (
                    await conn.execute("select id from signals where public_id=%s", (accepted.json()["public_id"],))
                ).fetchone()
            )[0]
        await svc.submit(sid, interactive=True)
        for _ in range(16):
            await public_cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            iid, status, original_ar, ar_status = await (
                await conn.execute(
                    "select i.id,i.status,a.id,a.outcome from incidents i join incident_signals x on x.incident_id=i.id join agent_runs a on a.signal_id=x.signal_id and a.kind='agent' where x.signal_id=%s",
                    (sid,),
                )
            ).fetchone()
            assert status == "escalated" and ar_status == "deferred"
            first_notice = (
                await (
                    await conn.execute(
                        "select created_at from notifications where signal_id=%s and template_code='demo_unresolved'",
                        (sid,),
                    )
                ).fetchone()
            )[0]
            assert (
                await (
                    await conn.execute(
                        "select distinct payload->>'outcome' from team_actions where incident_id=%s", (iid,)
                    )
                ).fetchall()
            ) == [(initial,)]
            await recover_public_cases(app, conn, rid, now=first_notice + dt.timedelta(seconds=1))
            assert (
                await (
                    await conn.execute(
                        "select count(*) from team_actions where incident_id=%s and payload->>'outcome'='recovered'",
                        (iid,),
                    )
                ).fetchone()
            )[0] == 0
        if trigger == "repeat":
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                await conn.execute("update personal_chat_sessions set last_message_at=now()-interval '3 seconds'")
            repeat = client.post(
                "/api/personal/messages",
                json={**payload, "request_id": str(uuid.uuid4()), "text": "Проблема сохраняется. " + payload["text"]},
            )
            assert repeat.status_code == 202
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                repeat_sid = (
                    await (
                        await conn.execute("select id from signals where public_id=%s", (repeat.json()["public_id"],))
                    ).fetchone()
                )[0]
            await svc.submit(repeat_sid, interactive=True)
        now = first_notice + dt.timedelta(seconds=31 if trigger == "timer" else 1)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await recover_public_cases(app, conn, rid, now=now)
            await recover_public_cases(app, conn, rid, now=now)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from team_actions where incident_id=%s and action='fix_decision' and payload->>'outcome'='recovered'",
                        (iid,),
                    )
                ).fetchone()
            )[0] == 1
        for _ in range(16):
            await public_cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone())[
                0
            ] == "closed"
            assert (
                await (await conn.execute("select outcome from agent_runs where id=%s", (original_ar,))).fetchone()
            )[0] == "completed"
            assert (
                await (
                    await conn.execute(
                        "select template_code from notifications where signal_id=%s and template_code in ('demo_unresolved','resolved') order by id",
                        (sid,),
                    )
                ).fetchall()
            ) == [("demo_unresolved",), ("resolved",)]
            config = await configuration(conn, rid)
            assert config["outcome_cursor"] == OUTCOMES.index(initial) + 1
            assert config["incident_outcomes"] == {str(iid): initial}
            assert (await (await conn.execute("select count(*) from incidents where run_id=%s", (rid,))).fetchone())[
                0
            ] == 1
            if trigger == "repeat":
                assert (await (await conn.execute("select status from signals where id=%s", (repeat_sid,))).fetchone())[
                    0
                ] == "closed"
        assert sim.run_id == bank_run and sim.clock.sim_time == before and not sim.clock.running
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
