"""T-063: отложенные follow-up (сценарий 5 deferred_fraud)."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from app.agent.graph import wake_due_followups, wake_followups_for_incident
from app.agent.runner import AgentService
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from tests.helpers import advance_sim, dsn, mock_chain, new_run, run_agent_on, sim_now

pytestmark = pytest.mark.integration

PROFILE = LLMProfile(code="mock", provider="mock", model="mock-1", role="main")
FRAUD_TEXT = (
    "Вижу подозрительную операцию на 4 500 руб. в магазине, которую я не совершал. Похоже на мошенников. Что делать?"
)


async def test_incident_virtual_time_does_not_wake_other_client(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "independent clocks")
        mass = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        premium = (
            await (
                await conn.execute("select id from clients where segment_code='premium' order by id limit 1")
            ).fetchone()
        )[0]
        one, state = await run_agent_on(
            conn, "Не открывается вклад в мобильном приложении, ошибка 503", client_id=mass, run_id=rid
        )
        two, _ = await run_agent_on(conn, FRAUD_TEXT, client_id=premium, run_id=rid, origin="sim")
        iid = (
            await (await conn.execute("select incident_id from incident_signals where signal_id=%s", (one,))).fetchone()
        )[0]
        before = await sim_now(conn)
        other = await (
            await conn.execute("select id,status from followups where signal_id=%s and status='scheduled'", (two,))
        ).fetchone()
        assert other
        await wake_followups_for_incident(
            conn, incident_id=iid, sim_time=before + dt.timedelta(days=7), chain=mock_chain(), profile=PROFILE
        )
        assert (await (await conn.execute("select status from followups where id=%s", (other[0],))).fetchone())[
            0
        ] == "scheduled"
        assert await sim_now(conn) == before


@pytest.mark.asyncio
async def test_deferred_fraud_wake_silence_escalation(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "t063-deferred", scenario_id="deferred_fraud")
        row = await (
            await conn.execute(
                "select id from clients where segment_code = 'premium' and is_active order by id limit 1"
            )
        ).fetchone()
        assert row
        signal_id, state = await run_agent_on(conn, FRAUD_TEXT, client_id=int(row[0]), run_id=run_id)
        assert state.get("outcome") == "deferred"
        fup = await (
            await conn.execute(
                "select id, status from followups where signal_id = %s order by id desc limit 1", (signal_id,)
            )
        ).fetchone()
        assert fup and fup[1] == "scheduled"
        sim_time = await advance_sim(conn, 25)
        n = await wake_due_followups(conn, sim_time=sim_time, chain=mock_chain(), profile=PROFILE)
        assert n >= 1
        esc = await (await conn.execute("select id from escalations where signal_id = %s", (signal_id,))).fetchone()
        assert esc
        sig = await (await conn.execute("select status from signals where id = %s", (signal_id,))).fetchone()
        assert sig and sig[0] == "closed"
        dup = await (
            await conn.execute("select count(*) from followups where signal_id = %s and status = 'fired'", (signal_id,))
        ).fetchone()
        fired_before = int(dup[0]) if dup else 0
        n2 = await wake_due_followups(conn, sim_time=sim_time, chain=mock_chain(), profile=PROFILE)
        assert n2 == 0
        dup2 = await (
            await conn.execute("select count(*) from followups where signal_id = %s and status = 'fired'", (signal_id,))
        ).fetchone()
        assert int(dup2[0]) == fired_before


@pytest.mark.asyncio
async def test_deferred_list_api(seeded: str) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "t063-api")
        row = await (await conn.execute("select id from clients where segment_code = 'premium' limit 1")).fetchone()
        signal_id, _ = await run_agent_on(conn, FRAUD_TEXT, client_id=int(row[0]), run_id=run_id)
        assert signal_id
    tc = TestClient(app)
    r = tc.get("/api/signals/deferred")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["signal_id"] == signal_id and it.get("signal") and it.get("followup") for it in items)


@pytest.mark.asyncio
async def test_recover_wakes_overdue_followup(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "t063-recover")
        row = await (await conn.execute("select id from clients where segment_code = 'premium' limit 1")).fetchone()
        signal_id, _ = await run_agent_on(conn, FRAUD_TEXT, client_id=int(row[0]), run_id=run_id)
        await conn.execute(
            "update followups set wake_sim = (select sim_time - interval '1 hour' from sim_state where id = 1) "
            "where signal_id = %s and status = 'scheduled'",
            (signal_id,),
        )
        await conn.commit()
    svc = AgentService(ProviderChain([MockProvider()]), PROFILE, dsn=dsn(seeded), concurrency=1)
    await svc._recover()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        st = await (await conn.execute("select status from followups where signal_id = %s", (signal_id,))).fetchone()
        assert st and st[0] == "fired"


@pytest.mark.asyncio
async def test_public_reply_wakes_only_its_parent_without_advancing_clock(seeded: str, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    token = "isolated_tracking_capability_123456789"
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid = await new_run(conn, "public reply paused clock")
            premium = (
                await (
                    await conn.execute("select id from clients where segment_code='premium' order by id limit 1")
                ).fetchone()
            )[0]
            parent, _ = await run_agent_on(conn, FRAUD_TEXT, client_id=premium, run_id=rid, origin="sim")
            other_client = (
                await (
                    await conn.execute(
                        "select id from clients where segment_code='premium' and id<>%s order by id limit 1", (premium,)
                    )
                ).fetchone()
            )[0]
            other, _ = await run_agent_on(
                conn, FRAUD_TEXT + " Ещё одна операция.", client_id=other_client, run_id=rid, origin="sim"
            )
            assert (
                await (
                    await conn.execute(
                        "select count(*) from followups where signal_id=%s and reason='awaiting_client' and status='scheduled'",
                        (other,),
                    )
                ).fetchone()
            )[0] >= 1
            await conn.execute("update signals set tracking_token=%s where id=%s", (token, parent))
            before = await sim_now(conn)
            pending = await (
                await conn.execute(
                    "select id from followups where signal_id=%s and reason='awaiting_client' and status='scheduled'",
                    (parent,),
                )
            ).fetchone()
            assert pending
            await conn.commit()
        with TestClient(create_app()) as client:
            viewed = client.get(f"/api/public/track/{token}")
            assert viewed.status_code == 200 and viewed.json()["can_append"]
            assert viewed.json()["question_from_agent"]
            assert (
                client.post(
                    f"/api/public/track/{token}", json={"text": "Операция была вчера в 10:00, карту уже заблокировал"}
                ).status_code
                == 202
            )
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            child_row = await (
                await conn.execute("select id,run_id from signals where parent_signal_id=%s", (parent,))
            ).fetchone()
            assert child_row and child_row[1] == rid
            child = child_row[0]
        svc = AgentService(mock_chain(), PROFILE, dsn=dsn(seeded), concurrency=1)
        task = svc.submit_client_reply(parent, child, before)
        assert svc.submit_client_reply(parent, child, before) is task
        await task
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            # Краткий ответ требует HITL: parent не продолжается до штатного одобрения.
            assert (await (await conn.execute("select status from signals where id=%s", (child,))).fetchone())[
                0
            ] == "awaiting_human"
            assert (await (await conn.execute("select status from followups where id=%s", (pending[0],))).fetchone())[
                0
            ] == "scheduled"
            decision = (
                await (
                    await conn.execute(
                        "select id from human_decisions where signal_id=%s and decision is null", (child,)
                    )
                ).fetchone()
            )[0]
            await conn.execute(
                "update human_decisions set decision='accept',decided_by='test',decided_at=now() where id=%s",
                (decision,),
            )
            await conn.commit()
            from app.agent.graph import resume_after_human

            approved = await resume_after_human(
                conn, human_decision_id=decision, chain=mock_chain(), profile=PROFILE, sim_time=before
            )
            assert approved and approved["outcome"] != "awaiting_human"
        await svc.submit_client_reply(parent, child, before)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select status from followups where id=%s", (pending[0],))).fetchone())[
                0
            ] == "fired"
            assert (await (await conn.execute("select status from signals where id=%s", (parent,))).fetchone())[
                0
            ] not in ("awaiting_client", "error")
            assert (
                await (
                    await conn.execute(
                        "select count(*) from followups where signal_id=%s and reason='awaiting_client' and status='scheduled'",
                        (other,),
                    )
                ).fetchone()
            )[0] >= 1
            assert await sim_now(conn) == before
    finally:
        get_settings.cache_clear()
