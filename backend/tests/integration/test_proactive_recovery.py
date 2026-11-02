"""Поздний impact: один native service/AR, PostgreSQL checkpoint, без повторного LLM."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest

from app.agent import graph, proactive
from app.agent.graph import process_signal, recover_agent_run, resume_proactive_fault
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

from .test_proactive_fault import fault, operation


async def prepare(conn):
    run = await new_run(conn, "T039 late impact")
    at = await sim_now(conn)
    people = [r[0] for r in await (await conn.execute("select id from clients order by id limit 2")).fetchall()]
    for client in people:
        await conn.execute(
            "update clients set consents=jsonb_build_object('proactive',true), "
            "contacts=contacts||jsonb_build_object('preferred','chat') where id=%s",
            (client,),
        )
    fid = await fault(conn, run, at)
    await operation(conn, run, fid, people[0], at)
    [sid] = await proactive.produce(conn)
    await conn.commit()
    state = await process_signal(conn, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE)
    assert state["outcome"] == "deferred" and state["client"] is None
    totals = await (
        await conn.execute(
            "select total_tokens,prompt_tokens,completion_tokens from agent_runs where id=%s", (state["agent_run_id"],)
        )
    ).fetchone()
    return run, fid, sid, people, at, state, totals


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_late_native_recipients_resume_same_checkpoint_without_model_or_unknown_retry(seeded, unknown):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, initial, totals = await prepare(conn)
        if unknown:
            await conn.execute(
                "update notifications set status='unknown',sent_sim=null,sent_at=null "
                "where run_id=%s and template_code='proactive_fault'",
                (run,),
            )
        later = at + dt.timedelta(minutes=1)
        await operation(conn, run, fid, people[1], later)
        await conn.execute("update sim_state set sim_time=%s where id=1", (later,))
        assert await proactive.produce(conn) == [sid]
        await conn.commit()
    # Другие соединение/Deps/graph: Python state прежнего прохода не переиспользуется.
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as restarted:
        state = await resume_proactive_fault(restarted, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE)
        assert state is not None and state["agent_run_id"] == initial["agent_run_id"]
        assert state["decision"] == initial["decision"]
        assert state["outcome"] == "deferred"
        assert await (
            await restarted.execute("select count(*) from agent_runs where signal_id=%s and kind='agent'", (sid,))
        ).fetchone() == (1,)
        assert (
            await (
                await restarted.execute(
                    "select total_tokens,prompt_tokens,completion_tokens from agent_runs where id=%s",
                    (state["agent_run_id"],),
                )
            ).fetchone()
            == totals
        )
        calls = await (
            await restarted.execute(
                "select node,count(*) from agent_steps where run_id=%s "
                "and node in ('normalize','classify','decide') group by node",
                (state["agent_run_id"],),
            )
        ).fetchall()
        assert dict(calls) == {"normalize": 1, "classify": 1, "decide": 1}
        assert await (
            await restarted.execute(
                "select count(*) from followups where agent_run_id=%s and status='scheduled'", (state["agent_run_id"],)
            )
        ).fetchone() == (1,)
        notices = await (
            await restarted.execute(
                "select client_id,status,sent_sim from notifications "
                "where run_id=%s and template_code='proactive_fault' order by client_id",
                (run,),
            )
        ).fetchall()
        assert notices == [
            (people[0], "unknown" if unknown else "sent", None if unknown else at),
            (people[1], "sent", later),
        ]
        assert await (
            await restarted.execute("select mass_impact from incidents where run_id=%s", (run,))
        ).fetchone() == (2,)
        assert await (
            await restarted.execute("select affected_count from incident_economics where run_id=%s", (run,))
        ).fetchone() == (2,)
        assert await resume_proactive_fault(restarted, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE) is None
        assert await (
            await restarted.execute(
                "select count(*) from notifications where run_id=%s and template_code='proactive_fault'", (run,)
            )
        ).fetchone() == (2,)


@pytest.mark.asyncio
async def test_cancelled_late_entry_recovers_same_durable_thread_without_model(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, initial, totals = await prepare(conn)
        later = at + dt.timedelta(minutes=1)
        await operation(conn, run, fid, people[1], later)
        await conn.execute("update sim_state set sim_time=%s where id=1", (later,))
        await conn.commit()
        original = graph.NODES["act"]
        entered, release = asyncio.Event(), asyncio.Event()

        async def interrupted_entry(state, deps):
            entered.set()
            await release.wait()
            return await original(state, deps)

        monkeypatch.setitem(graph.NODES, "act", interrupted_entry)
        task = asyncio.create_task(
            resume_proactive_fault(conn, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE)
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        monkeypatch.setitem(graph.NODES, "act", original)
        assert await (
            await conn.execute("select outcome from agent_runs where id=%s", (initial["agent_run_id"],))
        ).fetchone() == (None,)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as restarted:
        state = await recover_agent_run(
            restarted, agent_run_id=initial["agent_run_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=later
        )
        assert state is not None and state["agent_run_id"] == initial["agent_run_id"]
        assert state["decision"] == initial["decision"]
        assert state["outcome"] == "deferred"
        assert (
            await (
                await restarted.execute(
                    "select total_tokens,prompt_tokens,completion_tokens from agent_runs where id=%s",
                    (state["agent_run_id"],),
                )
            ).fetchone()
            == totals
        )
        assert await (
            await restarted.execute(
                "select count(*) from notifications where run_id=%s and template_code='proactive_fault'", (run,)
            )
        ).fetchone() == (2,)
        assert await (
            await restarted.execute(
                "select count(*) from followups where agent_run_id=%s and status='scheduled'", (state["agent_run_id"],)
            )
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_parallel_late_wakeups_keep_single_ar_followup_and_recipient(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, initial, totals = await prepare(conn)
        later = at + dt.timedelta(minutes=1)
        await operation(conn, run, fid, people[1], later)
        await conn.execute("update sim_state set sim_time=%s where id=1", (later,))
        await conn.commit()

    async def wake():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as restarted:
            return await resume_proactive_fault(restarted, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE)

    results = await asyncio.gather(wake(), wake())
    assert sum(result is not None for result in results) == 1
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as check:
        assert await (
            await check.execute("select count(*) from agent_runs where signal_id=%s and kind='agent'", (sid,))
        ).fetchone() == (1,)
        assert await (
            await check.execute(
                "select count(*) from notifications where run_id=%s and template_code='proactive_fault'", (run,)
            )
        ).fetchone() == (2,)
        assert await (
            await check.execute(
                "select count(*) from followups where agent_run_id=%s and status='scheduled'",
                (initial["agent_run_id"],),
            )
        ).fetchone() == (1,)
