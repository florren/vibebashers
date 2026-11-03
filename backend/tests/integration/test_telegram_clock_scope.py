"""ACK доставки хранит реальные часы и не заимствует sim clock чужого run."""

import asyncio
import datetime as dt

import pytest

from app.sim.runs import create_run
from app.tgbot.delivery import deliver_once
from tests.integration import test_tgbot_delivery as helpers
from tests.integration.test_tgbot_delivery import CONFIG, Sender, connect, queued, statuses

delivery_db = helpers.delivery_db


@pytest.mark.parametrize("scope,days", [("same", 1), ("foreign", -1), ("foreign", 1), ("none", -1)])
async def test_pending_delivery_does_not_borrow_foreign_clock(delivery_db, scope, days):
    async with await connect(delivery_db) as conn:
        original = await (await conn.execute("select current_run_id,sim_time from sim_state where id=1")).fetchone()
    nid = await queued(delivery_db)
    gate = asyncio.Event()
    sender = Sender(gate=gate)
    task = asyncio.create_task(deliver_once(CONFIG, sender, dsn=delivery_db))
    try:
        await asyncio.wait_for(sender.entered.wait(), 5)
        changed = original["sim_time"] + dt.timedelta(days=days)
        async with await connect(delivery_db) as conn, conn.transaction():
            if scope == "foreign":
                run = await create_run(
                    conn,
                    kind="live",
                    label="chronology foreign clock",
                    seed=42,
                    sim_time=changed,
                    reset_mode="counters",
                )
                assert run != original["current_run_id"]
            elif scope == "none":
                await conn.execute("update sim_state set current_run_id=null where id=1")
            await conn.execute("update sim_state set sim_time=%s where id=1", (changed,))
        gate.set()
        assert await asyncio.wait_for(task, 5)
        row = await statuses(delivery_db, nid)
        assert row["status"] == row["receipt"] == "sent"
        assert row["sent_at"] is not None
        assert row["sent_sim"] == (changed if scope == "same" else None)
        assert len(sender.calls) == 1
    finally:
        gate.set()
        await asyncio.gather(task, return_exceptions=True)
