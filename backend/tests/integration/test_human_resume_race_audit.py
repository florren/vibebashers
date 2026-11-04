"""Детерминированная граница HITL→timer: штатный граф, только MockProvider."""

import asyncio
import datetime as dt

import psycopg
import pytest

from app.agent import graph
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now


@pytest.mark.parametrize("scoped", [False, True])
async def test_timer_cannot_consume_followup_while_human_resume_still_running(seeded, monkeypatch, scoped):
    chain = mock_chain()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "human resume race audit")
        now = await sim_now(conn)
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' and is_active limit 1")
            ).fetchone()
        )[0]
        sig = await create_signal(
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
        state = await graph.process_signal(
            conn, signal_id=sig["signal_id"], chain=chain, profile=MOCK_PROFILE, sim_time=now
        )
        assert state["outcome"] == "awaiting_human"
        arid = state["agent_run_id"]
        assert (await (await conn.execute("select count(*) from followups where agent_run_id=%s", (arid,))).fetchone())[
            0
        ] == 0
        hid = (await (await conn.execute("select id from human_decisions where agent_run_id=%s", (arid,))).fetchone())[
            0
        ]
        await conn.execute("update human_decisions set decision='accept',decided_by='test' where id=%s", (hid,))
        await conn.commit()
    paused = asyncio.Event()
    release = asyncio.Event()
    original = graph._execute_node

    async def pause(node, state, deps, conn):
        if node == "followup_monitor" and state["agent_run_id"] == arid:
            paused.set()
            await release.wait()
        return await original(node, state, deps, conn)

    monkeypatch.setattr(graph, "_execute_node", pause)

    async def human():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as c:
            return await graph.resume_after_human(
                c, human_decision_id=hid, chain=chain, profile=MOCK_PROFILE, sim_time=now
            )

    task = asyncio.create_task(human())
    try:
        await asyncio.wait_for(paused.wait(), 15)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as timer:
            before = (await (await timer.execute("select outcome from agent_runs where id=%s", (arid,))).fetchone())[0]
            assert before is None  # Accepted entry уже сохранён; активный владелец исключает recovery.
            recovered = await graph.recover_agent_run(
                timer, agent_run_id=arid, chain=chain, profile=MOCK_PROFILE, sim_time=now
            )
            assert recovered is None
            count = (
                await (
                    await timer.execute(
                        "select count(*)from followups where agent_run_id=%s and status='scheduled'", (arid,)
                    )
                ).fetchone()
            )[0]
            assert count == 1
            n = await graph.wake_due_followups(
                timer,
                sim_time=now + dt.timedelta(days=2),
                chain=chain,
                profile=MOCK_PROFILE,
                run_id=rid if scoped else None,
            )
            status = (
                await (await timer.execute("select status from followups where agent_run_id=%s", (arid,))).fetchone()
            )[0]
            assert n == 0
            assert status == "scheduled", "Timer consumed human-resume followup before its monitor checkpoint exists"
    finally:
        release.set()
        result = await asyncio.wait_for(task, 15)
    assert result["outcome"] == "deferred"


@pytest.mark.parametrize("failure", ["exception", "cancel"])
async def test_human_resume_releases_session_owner_after_failure(seeded, monkeypatch, failure):
    chain = mock_chain()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "human owner cleanup audit")
        now = await sim_now(conn)
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' and is_active limit 1")
            ).fetchone()
        )[0]
        sig = await create_signal(
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
        state = await graph.process_signal(
            conn, signal_id=sig["signal_id"], chain=chain, profile=MOCK_PROFILE, sim_time=now
        )
        assert state["outcome"] == "awaiting_human"
        arid = state["agent_run_id"]
        hid = (await (await conn.execute("select id from human_decisions where agent_run_id=%s", (arid,))).fetchone())[
            0
        ]
        await conn.execute("update human_decisions set decision='accept',decided_by='test' where id=%s", (hid,))
        await conn.commit()
        entered = asyncio.Event()

        async def fail(*args, **kwargs):
            entered.set()
            if failure == "cancel":
                await asyncio.Event().wait()
            raise ValueError("synthetic human owner cleanup")

        monkeypatch.setattr(graph, "load_deps", fail)
        task = asyncio.create_task(
            graph.resume_after_human(conn, human_decision_id=hid, chain=chain, profile=MOCK_PROFILE, sim_time=now)
        )
        await asyncio.wait_for(entered.wait(), 10)
        if failure == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
            await task
        # Исходное соединение открыто: его закрытие не должно скрывать утечку session lock.
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as observer:
            got = (
                await (
                    await observer.execute(
                        "select pg_try_advisory_lock(hashtextextended('agent-resume:'||%s::text,0))", (arid,)
                    )
                ).fetchone()
            )[0]
            assert got
            await observer.execute("select pg_advisory_unlock(hashtextextended('agent-resume:'||%s::text,0))", (arid,))
            await observer.commit()
        assert (await (await conn.execute("select 1")).fetchone())[0] == 1


@pytest.mark.parametrize("boundary", ["before_entry", "after_entry", "post_durable_entry"])
async def test_timer_crash_boundary_preserves_native_continuation(seeded, monkeypatch, boundary):
    chain = mock_chain()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "timer crash entry audit")
        now = await sim_now(conn)
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' and is_active limit 1")
            ).fetchone()
        )[0]
        sig = await create_signal(
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
        state = await graph.process_signal(
            conn, signal_id=sig["signal_id"], chain=chain, profile=MOCK_PROFILE, sim_time=now
        )
        assert state["outcome"] == "awaiting_human"
        arid = state["agent_run_id"]
        hid = (await (await conn.execute("select id from human_decisions where agent_run_id=%s", (arid,))).fetchone())[
            0
        ]
        await conn.execute("update human_decisions set decision='accept',decided_by='test' where id=%s", (hid,))
        await conn.commit()
        resumed = await graph.resume_after_human(
            conn, human_decision_id=hid, chain=chain, profile=MOCK_PROFILE, sim_time=now
        )
        assert resumed["outcome"] == "deferred"
        target = (
            "_execute_node"
            if boundary == "post_durable_entry"
            else "_resume_after_followup_owned"
            if boundary == "before_entry"
            else "run_graph"
        )
        original = getattr(graph, target)

        async def crash(*args, **kwargs):
            raise RuntimeError("synthetic crash entry boundary")

        monkeypatch.setattr(graph, target, crash)
        with pytest.raises(RuntimeError, match="synthetic crash entry boundary"):
            await graph.wake_due_followups(
                conn, sim_time=now + dt.timedelta(days=2), chain=chain, profile=MOCK_PROFILE, run_id=rid
            )
        monkeypatch.setattr(graph, target, original)
        outcome = (await (await conn.execute("select outcome from agent_runs where id=%s", (arid,))).fetchone())[0]
        if boundary == "post_durable_entry":
            assert outcome is None, "Fixture did not reach durable fresh graph entry"
        if boundary == "before_entry" or outcome == "deferred":
            # Атомарный entry откатывает весь claim; штатный timer должен повторить его.
            assert outcome == "deferred"
            assert (
                await (
                    await conn.execute(
                        "select status from followups where agent_run_id=%s order by id desc limit 1", (arid,)
                    )
                ).fetchone()
            )[0] == "scheduled"
            assert (
                await graph.wake_due_followups(
                    conn, sim_time=now + dt.timedelta(days=2), chain=chain, profile=MOCK_PROFILE, run_id=rid
                )
                == 1
            )
        else:
            # Если entry уже сохранён, штатный recovery обязан продолжить именно его.
            assert outcome is None
            result = await graph.recover_agent_run(
                conn, agent_run_id=arid, chain=chain, profile=MOCK_PROFILE, sim_time=now + dt.timedelta(days=2)
            )
            assert result is not None
            assert (await (await conn.execute("select outcome from agent_runs where id=%s", (arid,))).fetchone())[
                0
            ] is not None, "Durable recovery left AR NULL after timer-entry crash"


async def test_decided_human_crash_after_durable_act_is_recovered_or_marked_interrupted(seeded, monkeypatch):
    from app.agent.runner import AgentService
    from app.llm.mock import MockProvider

    calls = {"llm": 0}
    complete = MockProvider.complete_structured

    async def counted(self, *args, **kwargs):
        calls["llm"] += 1
        return await complete(self, *args, **kwargs)

    monkeypatch.setattr(MockProvider, "complete_structured", counted)

    async def effects(conn, rid):
        result = {}
        for name in ("notifications", "tasks", "ledger_entries"):
            result[name] = await (
                await conn.execute(
                    psycopg.sql.SQL(
                        "select count(*),md5(coalesce(string_agg(md5(row_to_json(t)::text),''order by id),'')) from {} t where run_id=%s"
                    ).format(psycopg.sql.Identifier(name)),
                    (rid,),
                )
            ).fetchone()
        return result

    chain = mock_chain()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "decided human restart audit")
        now = await sim_now(conn)
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' and is_active limit 1")
            ).fetchone()
        )[0]
        sig = await create_signal(
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
        state = await graph.process_signal(
            conn, signal_id=sig["signal_id"], chain=chain, profile=MOCK_PROFILE, sim_time=now
        )
        assert state["outcome"] == "awaiting_human"
        arid = state["agent_run_id"]
        hid = (await (await conn.execute("select id from human_decisions where agent_run_id=%s", (arid,))).fetchone())[
            0
        ]
        await conn.execute("update human_decisions set decision='accept',decided_by='test' where id=%s", (hid,))
        await conn.commit()
        original = graph._execute_node

        async def crash(node, state, deps, conn):
            if node == "followup_monitor":
                raise RuntimeError("synthetic crash after durable human act")
            return await original(node, state, deps, conn)

        monkeypatch.setattr(graph, "_execute_node", crash)
        with pytest.raises(RuntimeError, match="synthetic crash after durable human act"):
            await graph.resume_after_human(conn, human_decision_id=hid, chain=chain, profile=MOCK_PROFILE, sim_time=now)
        monkeypatch.setattr(graph, "_execute_node", original)
        await conn.execute("update sim_runs set status='running'where id=%s", (rid,))
        await conn.commit()
        before = (await (await conn.execute("select count(*)from notifications where run_id=%s", (rid,))).fetchone())[0]
        assert before > 0
        committed_effects = await effects(conn, rid)
        committed_decision = await (
            await conn.execute(
                "select decision,modified_proposal,decided_by,decided_at from human_decisions where id=%s", (hid,)
            )
        ).fetchone()
        calls_before_restart = calls["llm"]
        assert calls_before_restart > 0
    service = AgentService(chain, MOCK_PROFILE, dsn=dsn(seeded), concurrency=1)
    await service._recover()
    if service._inflight:
        await asyncio.gather(*list(service._inflight))
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        row = await (
            await conn.execute(
                "select a.outcome,a.interrupted_at,h.decision from agent_runs a join human_decisions h on h.agent_run_id=a.id where a.id=%s",
                (arid,),
            )
        ).fetchone()
        assert row[2] == "accept"
        assert await effects(conn, rid) == committed_effects
        assert (
            await (
                await conn.execute(
                    "select decision,modified_proposal,decided_by,decided_at from human_decisions where id=%s", (hid,)
                )
            ).fetchone()
            == committed_decision
        )
        assert calls["llm"] == calls_before_restart
        assert (await (await conn.execute("select count(*)from notifications where run_id=%s", (rid,))).fetchone())[
            0
        ] == before
        assert row[0] == "deferred" and row[1] is None
