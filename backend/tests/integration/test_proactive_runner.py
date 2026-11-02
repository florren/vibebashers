"""Durable recheck стартует один normal AR и продолжает тот же native fanout."""

import asyncio
import datetime as dt

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent.runner import AgentService
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

from .test_proactive_fault import fault, operation


@pytest.mark.asyncio
async def test_agent_service_rechecks_zero_impact_and_resumes_after_lost_notify_restart(seeded):
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(seeded))
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 durable producer queue")
        at = await sim_now(conn)
        clients = await (
            await conn.execute("select id from clients where segment_code='mass' order by id limit 2")
        ).fetchall()
        first, second = clients[0][0], clients[1][0]
        await conn.execute(
            "update clients set consents=%s,contacts=%s where id=any(%s)",
            (Jsonb({"proactive": True}), Jsonb({"preferred": "chat"}), [first, second]),
        )
        fid = await fault(conn, run, at)
        await conn.commit()
        await service._proactive_cycle()
        assert not service._inflight
        assert not await (await conn.execute("select 1 from signals where run_id=%s", (run,))).fetchone()
        await operation(conn, run, fid, first, at)
        await conn.commit()
        # Без доставки NOTIFY: periodic native recheck находит actual impact.
        await service._proactive_cycle()
        await asyncio.gather(*list(service._inflight))
        before = await (
            await conn.execute("select id,prompt_tokens,completion_tokens from agent_runs where sim_run_id=%s", (run,))
        ).fetchone()
        assert before is not None
        assert await (
            await conn.execute(
                "select count(*) from notifications where run_id=%s and template_code='proactive_fault' and status='sent'",
                (run,),
            )
        ).fetchone() == (1,)
        await service.stop()
        later = at + dt.timedelta(minutes=1)
        await operation(conn, run, fid, second, later)
        await conn.execute("update sim_state set sim_time=%s where id=1", (later,))
        await conn.commit()
        restarted = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(seeded))
        await restarted._proactive_cycle()
        await asyncio.gather(*list(restarted._inflight))
        assert restarted.failed == 0
        assert await (
            await conn.execute("select id,prompt_tokens,completion_tokens from agent_runs where sim_run_id=%s", (run,))
        ).fetchall() == [before]
        assert await (
            await conn.execute(
                "select count(*) from notifications where run_id=%s and template_code='proactive_fault' and status='sent'",
                (run,),
            )
        ).fetchone() == (2,)
        assert await (await conn.execute("select mass_impact from incidents where run_id=%s", (run,))).fetchone() == (
            2,
        )
        assert await (await conn.execute("select count(*) from followups where sim_run_id=%s", (run,))).fetchone() == (
            1,
        )
        await restarted.stop()
