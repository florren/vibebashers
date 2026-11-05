"""Freeze: активное продолжение followup нельзя одновременно восстанавливать как прерванный AR."""

from __future__ import annotations

import asyncio

import psycopg
import pytest

from app.agent import graph, nodes
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, run_agent_on

pytestmark = pytest.mark.integration


async def test_active_followup_owns_agent_run_against_recovery(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "Freeze followup/recovery owner")
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        sid, initial = await run_agent_on(
            conn, "Не открывается вклад в мобильном приложении, ошибка 503", client_id=cid, run_id=run
        )
        assert initial["outcome"] == "deferred"
        arid, due = await (
            await conn.execute(
                "select f.agent_run_id,f.wake_sim from followups f where f.signal_id=%s and f.status='scheduled' and f.reason='awaiting_team' order by f.id limit 1",
                (sid,),
            )
        ).fetchone()
        before = (await (await conn.execute("select max(seq) from agent_steps where run_id=%s", (arid,))).fetchone())[0]
        await conn.commit()

    reached, release = asyncio.Event(), asyncio.Event()
    original = nodes.Deps.begin_step
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as followup:

        async def pause_before_record(self, node):
            await original(self, node)
            if self.ctx.conn is followup and self.ctx.agent_run_id == arid and node == "followup_monitor":
                # resume_after_followup уже зафиксировал outcome=NULL и восстановил старый max(seq).
                reached.set()
                await release.wait()

        monkeypatch.setattr(nodes.Deps, "begin_step", pause_before_record)
        task = asyncio.create_task(
            graph.wake_due_followups(followup, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run)
        )
        recovered = None
        try:
            await asyncio.wait_for(reached.wait(), 10)
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as other:
                # Реальный restart/resume scanner видит NULL, но должен пропустить занятого владельца.
                visible = (
                    await (await other.execute("select outcome from agent_runs where id=%s", (arid,))).fetchone()
                )[0]
                assert visible is None
                recovered = await asyncio.wait_for(
                    graph.recover_agent_run(
                        other, agent_run_id=arid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=due
                    ),
                    10,
                )
        finally:
            release.set()
            result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert not isinstance(result, BaseException), repr(result)
        assert recovered is None
        assert result == 1

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rows = await (
            await conn.execute(
                "select seq,node,status from agent_steps where run_id=%s and seq>%s order by seq", (arid, before)
            )
        ).fetchall()
        assert rows == [(before + 1, "followup_monitor", "ok")]
        assert (await (await conn.execute("select outcome from agent_runs where id=%s", (arid,))).fetchone())[
            0
        ] == "deferred"
        assert (
            await (
                await conn.execute(
                    "select count(*) from followups where agent_run_id=%s and status='scheduled'", (arid,)
                )
            ).fetchone()
        )[0] == 1
        unlocked = (
            await (
                await conn.execute(
                    "select pg_try_advisory_lock(hashtextextended('agent-resume:' || %s::text,0))", (arid,)
                )
            ).fetchone()
        )[0]
        assert unlocked
        await conn.execute("select pg_advisory_unlock(hashtextextended('agent-resume:' || %s::text,0))", (arid,))


async def _deferred_case(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "Freeze continuation serialization")
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        sid, initial = await run_agent_on(
            conn, "Не открывается вклад в мобильном приложении, ошибка 503", client_id=cid, run_id=run
        )
        assert initial["outcome"] == "deferred"
        fid, arid, due = await (
            await conn.execute(
                "select id,agent_run_id,wake_sim from followups where signal_id=%s and reason='awaiting_team' and status='scheduled' order by id limit 1",
                (sid,),
            )
        ).fetchone()
        before = (await (await conn.execute("select max(seq) from agent_steps where run_id=%s", (arid,))).fetchone())[0]
        await conn.commit()
    return run, fid, arid, due, before


async def _assert_released(seeded, arid):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as observer:
        assert (
            await (
                await observer.execute(
                    "select pg_try_advisory_lock(hashtextextended('agent-resume:' || %s::text,0))", (arid,)
                )
            ).fetchone()
        )[0]
        await observer.execute("select pg_advisory_unlock(hashtextextended('agent-resume:' || %s::text,0))", (arid,))


async def test_followup_waits_for_active_recovery(seeded, monkeypatch):
    run, fid, arid, due, before = await _deferred_case(seeded)
    reached, release = asyncio.Event(), asyncio.Event()
    original = graph._restore_recording_state
    async with (
        await psycopg.AsyncConnection.connect(dsn(seeded)) as recovery,
        await psycopg.AsyncConnection.connect(dsn(seeded)) as followup,
    ):
        await recovery.execute(
            "update agent_runs set outcome=null,interrupted_at=clock_timestamp() where id=%s", (arid,)
        )
        await recovery.commit()

        async def pause(conn, deps):
            await original(conn, deps)
            if conn is recovery:
                reached.set()
                await release.wait()

        monkeypatch.setattr(graph, "_restore_recording_state", pause)
        first = asyncio.create_task(
            graph.recover_agent_run(recovery, agent_run_id=arid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=due)
        )
        second = None
        try:
            await asyncio.wait_for(reached.wait(), 10)
            second = asyncio.create_task(
                graph.wake_due_followups(followup, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run)
            )
            assert await asyncio.wait_for(second, 10) == 0
            assert (await (await followup.execute("select status from followups where id=%s", (fid,))).fetchone())[
                0
            ] == "scheduled"
        finally:
            release.set()
            results = await asyncio.gather(*([first, second] if second else [first]), return_exceptions=True)
        assert not any(isinstance(r, BaseException) for r in results), repr(results)
        assert results[0] is not None
        assert results[1] == 0
        # Terminal checkpoint искусственно помечен прерванным только для проверки порядка ownership;
        # штатное восстановление прерванного узла проверяется отдельно.
        assert (await (await followup.execute("select status from followups where id=%s", (fid,))).fetchone())[
            0
        ] == "scheduled"
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rows = await (
            await conn.execute(
                "select seq,status from agent_steps where run_id=%s and seq>%s order by seq", (arid, before)
            )
        ).fetchall()
        assert [r[0] for r in rows] == list(range(before + 1, before + 1 + len(rows)))
        assert sum(r[1] == "retry" for r in rows) == 1
        assert all(r[1] in {"ok", "retry"} for r in rows)
    await _assert_released(seeded, arid)


async def test_two_followups_serialize_same_agent_run(seeded, monkeypatch):
    import datetime as dt

    run, fid, arid, due, before = await _deferred_case(seeded)
    second_due = due + dt.timedelta(hours=1)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        await conn.execute(
            "insert into followups(sim_run_id,agent_run_id,signal_id,incident_id,wake_sim,reason,payload) select sim_run_id,agent_run_id,signal_id,incident_id,%s,reason,payload from followups where id=%s",
            (second_due, fid),
        )
        await conn.commit()
    reached, release = asyncio.Event(), asyncio.Event()
    original = nodes.Deps.begin_step
    async with (
        await psycopg.AsyncConnection.connect(dsn(seeded)) as first_conn,
        await psycopg.AsyncConnection.connect(dsn(seeded)) as second_conn,
    ):

        async def pause(self, node):
            await original(self, node)
            if self.ctx.conn is first_conn and node == "followup_monitor":
                reached.set()
                await release.wait()

        monkeypatch.setattr(nodes.Deps, "begin_step", pause)
        first = asyncio.create_task(
            graph.wake_due_followups(first_conn, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run)
        )
        second = None
        try:
            await asyncio.wait_for(reached.wait(), 10)
            second = asyncio.create_task(
                graph.wake_due_followups(
                    second_conn, sim_time=second_due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run
                )
            )
            assert await asyncio.wait_for(second, 10) == 0
        finally:
            release.set()
            results = await asyncio.gather(*([first, second] if second else [first]), return_exceptions=True)
        assert results == [1, 0], repr(results)
        assert (
            await graph.wake_due_followups(
                second_conn, sim_time=second_due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run
            )
            == 1
        )
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rows = await (
            await conn.execute(
                "select seq,node,status from agent_steps where run_id=%s and seq>%s order by seq", (arid, before)
            )
        ).fetchall()
        assert rows == [(before + 1, "followup_monitor", "ok"), (before + 2, "followup_monitor", "ok")]
    await _assert_released(seeded, arid)


@pytest.mark.parametrize("cancel", [False, True])
async def test_followup_releases_owner_after_failure(seeded, monkeypatch, cancel):
    _run, fid, arid, due, _before = await _deferred_case(seeded)
    reached = asyncio.Event()

    async def fail(*args, **kwargs):
        reached.set()
        if cancel:
            await asyncio.Event().wait()
        # Проверяем unlock также после aborted SQL transaction.
        await args[0].execute("select 1/0")

    monkeypatch.setattr(graph, "_resume_after_followup_owned", fail)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        task = asyncio.create_task(
            graph.resume_after_followup(conn, followup_id=fid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=due)
        )
        await asyncio.wait_for(reached.wait(), 10)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else psycopg.errors.DivisionByZero):
            await task
        assert (await (await conn.execute("select 1")).fetchone())[0] == 1
        await _assert_released(seeded, arid)


async def test_completed_run_sla_escalation_check_is_consumed_without_resume(seeded):
    run, fid, arid, due, before = await _deferred_case(seeded)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        await conn.execute("update agent_runs set outcome='completed' where id=%s", (arid,))
        check_id = (
            await (
                await conn.execute(
                    "insert into followups(sim_run_id,agent_run_id,signal_id,incident_id,wake_sim,reason,payload) select sim_run_id,agent_run_id,signal_id,incident_id,wake_sim,'escalation_check',payload from followups where id=%s returning id",
                    (fid,),
                )
            ).fetchone()
        )[0]
        await conn.commit()
        assert (
            await graph.wake_due_followups(conn, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run)
            == 0
        )
        assert (await (await conn.execute("select status from followups where id=%s", (check_id,))).fetchone())[
            0
        ] == "fired"
        assert (await (await conn.execute("select outcome from agent_runs where id=%s", (arid,))).fetchone())[
            0
        ] == "completed"
        assert (await (await conn.execute("select max(seq) from agent_steps where run_id=%s", (arid,))).fetchone())[
            0
        ] == before


@pytest.mark.parametrize("has_monitor", [True, False])
async def test_completed_run_sla_report_requires_checkpoint(seeded, has_monitor):
    run, fid, arid, due, before = await _deferred_case(seeded)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        await conn.execute("update agent_runs set outcome='completed' where id=%s", (arid,))
        await conn.execute("update followups set reason='report_due' where id=%s", (fid,))
        if not has_monitor:
            await conn.execute("delete from agent_steps where run_id=%s and node='followup_monitor'", (arid,))
        before_tasks = (
            await (
                await conn.execute("select count(*) from tasks where run_id=%s and kind='report_reminder'", (run,))
            ).fetchone()
        )[0]
        before_notifications = (
            await (await conn.execute("select count(*) from notifications where run_id=%s", (run,))).fetchone()
        )[0]
        await conn.commit()
        assert await graph.wake_due_followups(
            conn, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run
        ) == int(has_monitor)
        assert (await (await conn.execute("select status from followups where id=%s", (fid,))).fetchone())[0] == (
            "fired" if has_monitor else "scheduled"
        )
        assert (
            await (
                await conn.execute("select count(*) from tasks where run_id=%s and kind='report_reminder'", (run,))
            ).fetchone()
        )[0] == before_tasks + int(has_monitor)
        assert (await (await conn.execute("select count(*) from notifications where run_id=%s", (run,))).fetchone())[
            0
        ] == before_notifications  # Штатный notify_team дедуплицирует team_notice инцидента.
        if has_monitor:
            rows = await (
                await conn.execute(
                    "select seq,node,status from agent_steps where run_id=%s and seq>%s order by seq", (arid, before)
                )
            ).fetchall()
            assert rows == [(before + 1, "followup_monitor", "ok")]
            assert (
                await graph.wake_due_followups(conn, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run)
                == 0
            )


async def test_parked_timer_busy_owner_does_not_consume_followup(seeded):
    run, fid, arid, due, before = await _deferred_case(seeded)
    async with (
        await psycopg.AsyncConnection.connect(dsn(seeded)) as owner,
        await psycopg.AsyncConnection.connect(dsn(seeded)) as timer,
    ):
        await owner.execute("select pg_advisory_lock(hashtextextended('agent-resume:' || %s::text,0))", (arid,))
        try:
            assert (
                await asyncio.wait_for(
                    graph.wake_due_followups(timer, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run),
                    10,
                )
                == 0
            )
            assert (await (await timer.execute("select status from followups where id=%s", (fid,))).fetchone())[
                0
            ] == "scheduled"
            assert (
                await (await timer.execute("select max(seq) from agent_steps where run_id=%s", (arid,))).fetchone()
            )[0] == before
        finally:
            await owner.execute("select pg_advisory_unlock(hashtextextended('agent-resume:' || %s::text,0))", (arid,))
        assert (
            await graph.wake_due_followups(timer, sim_time=due, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run)
            == 1
        )
