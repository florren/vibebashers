"""Автоподарок старого контекста не использует часы другого запуска."""

import datetime as dt

import psycopg
import pytest

from app.agent.tools import write as wt
from app.agent.tools.base import ToolContext
from app.ingest.normalizer import create_signal, from_api_signal
from app.sim.runs import create_run
from tests.helpers import dsn, new_run, sim_now


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,days", [("same", 0), ("foreign", -1), ("foreign", 1), ("none", -1)])
async def test_automatic_gift_keeps_own_resolution_clock(seeded, scope, days):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "gift clock", kind="live")
        at = await sim_now(conn)
        receipt = await create_signal(
            conn,
            from_api_signal({"channel_code": "chat", "text": "Ошибка оплаты картой", "client_id": 1}),
            source_code="api",
            run_id=rid,
            sim_time=at,
        )
        assert receipt["status"] == "accepted"
        signal = receipt["signal_id"]
        agent = (
            await (
                await conn.execute(
                    "insert into agent_runs(sim_run_id,signal_id,client_id,prompt_version,started_sim) values(%s,%s,1,'gift-clock',%s) returning id",
                    (rid, signal, at),
                )
            ).fetchone()
        )[0]
        ctx = ToolContext(conn, run_id=rid, agent_run_id=agent, sim_time=at)
        incident = await wt.create_incident(
            ctx,
            signal,
            1,
            {
                "title_ru": "Ошибка оплаты картой",
                "team": "team_debit",
                "product": "debit_card",
                "sla": {"due_sim": at + dt.timedelta(days=2), "take_due_sim": at + dt.timedelta(hours=2)},
            },
        )
        iid = incident["incident_id"]
        task = await wt.create_task(
            ctx,
            "gift",
            iid,
            1,
            {
                "gift": {"gift_code": "bonus_points", "points": 600},
                "when": "after_resolved",
            },
        )
        await conn.commit()
        # Ровно граница approved T-161: исторический контекст сохраняет свои часы.
        if scope == "foreign":
            other = await create_run(
                conn,
                kind="live",
                label="gift foreign clock",
                seed=42,
                sim_time=at + dt.timedelta(days=days),
                reset_mode="counters",
            )
            assert other != rid
            await conn.execute("update sim_state set sim_time=%s where id=1", (at + dt.timedelta(days=days),))
        elif scope == "none":
            await conn.execute(
                "update sim_state set current_run_id=null,sim_time=%s where id=1", (at + dt.timedelta(days=days),)
            )
        await wt.update_incident(ctx, iid, "in_progress", "В работе")
        await wt.update_incident(ctx, iid, "resolved", "Услуга восстановлена")
        row = await (
            await conn.execute(
                "select n.run_id,n.sent_sim,t.resolved_sim,t.payload,i.resolved_sim from notifications n join tasks t on t.id=%s join incidents i on i.id=n.incident_id where n.incident_id=%s and n.template_code='gift_offer'",
                (task["task_id"], iid),
            )
        ).fetchone()
        assert row is not None
        assert row[0] == rid
        assert row[1] == row[2] == row[4] == at
        assert dt.datetime.fromisoformat(row[3]["issued"]["sim_time"]) == at
        assert row[3]["gift"]["points"] == 600
