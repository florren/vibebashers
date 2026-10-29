"""Подарок при act → resolved → gift остаётся одной задачей и одним уведомлением."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest

from app.agent import gifts
from app.agent.tools import write as wt
from app.agent.tools.base import ToolContext
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import dsn, new_run, sim_now

pytestmark = pytest.mark.integration


async def test_terminal_gift_reuses_issued_task_and_serializes_creation(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "terminal gift regression")
        now = await sim_now(conn)
        receipt = await create_signal(
            conn,
            from_api_signal({"channel_code": "chat", "text": "Ошибка оплаты дебетовой картой", "client_id": 1}),
            run_id=rid,
            source_code="api",
            emit_event=False,
        )
        signal_id = receipt["signal_id"]
        run = await (
            await conn.execute(
                "INSERT INTO agent_runs (sim_run_id,signal_id,client_id,prompt_version,started_sim) VALUES (%s,%s,1,'test',%s) RETURNING id",
                (rid, signal_id, now),
            )
        ).fetchone()
        assert run
        agent_id = run[0]
        ctx = ToolContext(conn, run_id=rid, agent_run_id=agent_id, sim_time=now)
        incident = await wt.create_incident(
            ctx,
            signal_id,
            1,
            {
                "title_ru": "Ошибка оплаты картой",
                "team": "team_debit",
                "product": "debit_card",
                "sla": {"due_sim": now + dt.timedelta(days=2), "take_due_sim": now + dt.timedelta(hours=2)},
            },
        )
        iid = incident["incident_id"]
        await conn.commit()

    payload = {"gift": {"gift_code": "bonus_points", "points": 600}, "when": "after_resolved"}

    async def create_gift() -> int:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            ctx = ToolContext(conn, run_id=rid, agent_run_id=agent_id, sim_time=now)
            result = await wt.create_task(ctx, "gift", iid, 1, payload)
            await conn.commit()
            return int(result["task_id"])

    first, second = await asyncio.gather(create_gift(), create_gift())
    assert first == second
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        ctx = ToolContext(conn, run_id=rid, agent_run_id=agent_id, sim_time=now)
        await wt.update_incident(ctx, iid, "in_progress", "проверка")
        await wt.update_incident(ctx, iid, "resolved", "услуга подтверждена")
        issued = await (await conn.execute("SELECT status,payload FROM tasks WHERE id=%s", (first,))).fetchone()
        assert issued and issued[0] == "done" and issued[1]["issued"]
        repeated = await wt.create_task(ctx, "gift", iid, 1, payload)
        assert repeated["task_id"] == first
        assert await gifts.issue_automatic(ctx, iid) == 0
        count = await (
            await conn.execute(
                "SELECT count(*) FROM notifications WHERE incident_id=%s AND template_code='gift_offer'", (iid,)
            )
        ).fetchone()
        assert count and count[0] == 1
        for status in ("approved", "changed", "rejected", "cancelled"):
            await conn.execute("UPDATE tasks SET status=%s,requires_hitl=true WHERE id=%s", (status, first))
            assert (await wt.create_task(ctx, "gift", iid, 1, payload))["task_id"] == first
            saved = await (
                await conn.execute("SELECT status,requires_hitl FROM tasks WHERE id=%s", (first,))
            ).fetchone()
            assert saved == (status, True)
        assert (
            await (
                await conn.execute("SELECT count(*) FROM tasks WHERE incident_id=%s AND kind='gift'", (iid,))
            ).fetchone()
        )[0] == 1
        # Иные задачи разрешено повторять после завершения.
        callback = await wt.create_task(ctx, "callback", iid, 1, {})
        await conn.execute("UPDATE tasks SET status='done' WHERE id=%s", (callback["task_id"],))
        assert (await wt.create_task(ctx, "callback", iid, 1, {}))["task_id"] != callback["task_id"]
        await conn.commit()
