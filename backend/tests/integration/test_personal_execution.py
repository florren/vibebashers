"""Публичный origin проходит ту же цепочку при паузе, включая опоздание и раздельные проблемы."""

import asyncio
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.agent.runner import AgentService
from app.api.demo_execution import DemoExecutionBody, post_demo_execution
from app.config import get_settings
from app.demo.execution import cycle
from app.main import create_app
from app.public_chat import create_public_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("late,empty_pointer", [(False, False), (True, False), (False, True)])
async def test_personal_full_chain_without_bank_clock(seeded, monkeypatch, late, empty_pointer):
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
        if late:
            await post_demo_execution(request, DemoExecutionBody(mode="simulation", team_outcome="late"))
        boot = client.get("/api/personal/session").json()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await conn.execute("update personal_chat_sessions set created_at=now()-interval '3 seconds'")
        payload = {
            "request_id": str(uuid.uuid4()),
            "form_token": boot["form_token"],
            "display_name": "Демо клиент",
            "voice": late,
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
        original = sim.clock.sim_time
        await asyncio.gather(svc.submit(first[0], interactive=True), svc.submit(sid, interactive=True))
        for _ in range(32):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        assert sim.run_id == first[1] and sim.run_id != 1
        assert not sim.clock.running and sim.clock.sim_time == original
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select s.id,s.status,i.id,i.product_code,i.status,i.sla_breached from signals s join incident_signals x on x.signal_id=s.id join incidents i on i.id=x.incident_id where s.id=any(%s) order by s.id",
                    ([first[0], sid],),
                )
            ).fetchall()
            assert len(rows) == 2 and len({r[2] for r in rows}) == 2
            assert all(r[1] == "closed" and r[4] == "closed" and r[5] == late for r in rows)
            finals = await (
                await conn.execute(
                    "select signal_id,body from notifications where signal_id=any(%s) and template_code='resolved' and status='sent'",
                    ([first[0], sid],),
                )
            ).fetchall()
            assert len(finals) == 2
        history = client.get("/api/personal/messages").json()
        assert len(history["messages"]) == 2
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
