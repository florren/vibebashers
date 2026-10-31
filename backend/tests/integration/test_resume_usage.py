"""Счётчики полного прогона сохраняются после HITL и повторных follow-up."""

from __future__ import annotations

import datetime as dt

import psycopg

from app.agent.graph import process_signal, resume_after_followup, resume_after_human
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from tests.helpers import MOCK_PROFILE, dsn, new_run, sim_now


class PaidMock(MockProvider):
    async def complete_structured(self, *args, **kwargs):
        obj, usage, raw = await super().complete_structured(*args, **kwargs)
        usage.cost_rub = 0.125
        return obj, usage, raw


async def assert_usage(conn, arid, expected_cost):
    row = await (
        await conn.execute(
            "select ar.prompt_tokens,ar.completion_tokens,ar.total_tokens,ar.total_latency_ms,ar.cost_estimate,"
            "coalesce(sum(st.prompt_tokens),0),coalesce(sum(st.completion_tokens),0),coalesce(sum(st.latency_ms),0) "
            "from agent_runs ar join agent_steps st on st.run_id=ar.id where ar.id=%s group by ar.id",
            (arid,),
        )
    ).fetchone()
    assert row[0] == row[5] > 0
    assert row[1] == row[6] > 0
    assert row[2] == row[5] + row[6]
    assert row[3] == row[7]
    assert float(row[4]) == expected_cost
    return row[2]


async def test_usage_survives_hitl_and_multiple_followups(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "resume usage regression")
        now = await sim_now(conn)
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' and is_active limit 1")
            ).fetchone()
        )[0]
        signal = await create_signal(
            conn,
            from_api_signal(
                {
                    "channel_code": "chat",
                    "client_id": cid,
                    "text": "Не могу открыть вклад: ошибка в мобильном приложении, деньги не списывались.",
                }
            ),
            source_code="api",
            run_id=rid,
            sim_time=now,
            emit_event=False,
        )
        await conn.commit()
        chain = ProviderChain([PaidMock()])
        state = await process_signal(
            conn, signal_id=signal["signal_id"], chain=chain, profile=MOCK_PROFILE, sim_time=now
        )
        assert state["outcome"] == "awaiting_human"
        arid = state["agent_run_id"]
        cost = float(
            (await (await conn.execute("select cost_estimate from agent_runs where id=%s", (arid,))).fetchone())[0]
        )
        assert cost > 0
        original = await assert_usage(conn, arid, cost)
        # Старый баг мог уже испортить итог AR: источник счётчиков — сохранённые шаги.
        await conn.execute(
            "update agent_runs set total_tokens=0,prompt_tokens=0,completion_tokens=0,total_latency_ms=0 where id=%s",
            (arid,),
        )
        hid = (await (await conn.execute("select id from human_decisions where agent_run_id=%s", (arid,))).fetchone())[
            0
        ]
        await conn.execute(
            "update human_decisions set decision='accept',decided_by='test',use_as_fewshot=false where id=%s", (hid,)
        )
        await conn.commit()
        await resume_after_human(conn, human_decision_id=hid, chain=chain, profile=MOCK_PROFILE, sim_time=now)
        assert await assert_usage(conn, arid, cost) >= original
        for turn in range(2):
            followup = await (
                await conn.execute(
                    "select id from followups where agent_run_id=%s and status='scheduled' and reason='awaiting_team' order by id desc limit 1",
                    (arid,),
                )
            ).fetchone()
            assert followup
            await resume_after_followup(
                conn,
                followup_id=followup[0],
                chain=chain,
                profile=MOCK_PROFILE,
                sim_time=now + dt.timedelta(hours=turn + 1),
            )
            assert await assert_usage(conn, arid, cost) >= original
