"""T-063: отложенные follow-up (сценарий 5 deferred_fraud)."""

from __future__ import annotations

import psycopg
import pytest

from app.agent.graph import wake_due_followups
from app.agent.runner import AgentService
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from tests.helpers import advance_sim, dsn, mock_chain, new_run, run_agent_on

pytestmark = pytest.mark.integration

PROFILE = LLMProfile(code="mock", provider="mock", model="mock-1", role="main")
FRAUD_TEXT = (
    "Вижу подозрительную операцию на 4 500 руб. в магазине, которую я не совершал. "
    "Похоже на мошенников. Что делать?"
)


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
        esc = await (
            await conn.execute("select id from escalations where signal_id = %s", (signal_id,))
        ).fetchone()
        assert esc
        sig = await (await conn.execute("select status from signals where id = %s", (signal_id,))).fetchone()
        assert sig and sig[0] == "closed"
        dup = await (
            await conn.execute(
                "select count(*) from followups where signal_id = %s and status = 'fired'", (signal_id,)
            )
        ).fetchone()
        fired_before = int(dup[0]) if dup else 0
        n2 = await wake_due_followups(conn, sim_time=sim_time, chain=mock_chain(), profile=PROFILE)
        assert n2 == 0
        dup2 = await (
            await conn.execute(
                "select count(*) from followups where signal_id = %s and status = 'fired'", (signal_id,)
            )
        ).fetchone()
        assert int(dup2[0]) == fired_before


@pytest.mark.asyncio
async def test_deferred_list_api(seeded: str) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "t063-api")
        row = await (
            await conn.execute("select id from clients where segment_code = 'premium' limit 1")
        ).fetchone()
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
        row = await (
            await conn.execute("select id from clients where segment_code = 'premium' limit 1")
        ).fetchone()
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
        st = await (
            await conn.execute("select status from followups where signal_id = %s", (signal_id,))
        ).fetchone()
        assert st and st[0] == "fired"
