"""Production phase worker + actual native graph/owner, no forced gold output."""

import asyncio

import psycopg
import pytest

from app.agent import proactive
from app.agent.runner import AgentService
from app.sim.proactive_scenario import case
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_proactive_prepare import mass_seeded as mass_seeded
from tests.integration.test_proactive_step import setup_case


@pytest.mark.asyncio
async def test_scripted_worker_runs_native_120_notice_care_30_dedupe_without_clock_hacks(
    mass_seeded, monkeypatch, record_property
):
    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim, concurrency=4)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert await proactive.produce(conn) == []
            await conn.commit()
        for _ in range(12):
            await service._proactive_cycle()
            if service._inflight:
                await asyncio.gather(*list(service._inflight))
            async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
                context = await case(conn, run)
                if "failed" in context.events:
                    pytest.fail(f"native phase failure: {context.events['failed']['payload']['reason']}")
                if "completed" in context.events:
                    break
        assert "completed" in context.events
        assert set(context.events) == {"prepared", "notified", "complaints", "completed"}
        assert service.failed == 0
        assert len(context.events["complaints"]["payload"]["complaint_signal_ids"]) == 30
        assert context.events["completed"]["payload"]["care_positive"] >= 90
        assert sim.clock.sim_time == context.observed_at
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert (
                await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()
            ) == (120,)
            assert (
                await (
                    await conn.execute("select count(*) from signals where run_id=%s and origin='proactive'", (run,))
                ).fetchone()
            ) == (1,)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from signals where run_id=%s and origin is distinct from 'proactive'", (run,)
                    )
                ).fetchone()
            ) == (30,)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from behavior_runtime where run_id=%s and first_complaint_sim is not null",
                        (run,),
                    )
                ).fetchone()
            ) == (30,)
            assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
            from app.sim import scenarios

            economics_before = await (
                await conn.execute("select to_jsonb(e) from incident_economics e where run_id=%s", (run,))
            ).fetchall()
            result = await scenarios.evaluate(conn, scenarios.get("mass_notifications"), run)
            assert result["passed"], result["checks"]
            assert all(check["ok"] is True for check in result["checks"])
            assert result["counts"]["prevented_complaints"] is None
            assert result["counts"]["notified_before_first_complaint"] >= 90
            assert (
                await (
                    await conn.execute("select to_jsonb(e) from incident_economics e where run_id=%s", (run,))
                ).fetchall()
                == economics_before
            )
            before = await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()
        # Completed journal remains source of truth after service/Simulator restart.
        await service.stop()
        await sim.shutdown()
        from app.sim.engine import Simulator

        sim = Simulator(dsn=dsn(mass_seeded))
        await sim.load_state()
        service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim)
        await service._proactive_cycle()
        if service._inflight:
            await asyncio.gather(*list(service._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert (
                await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone() == before
            )
            assert (
                await (
                    await conn.execute("select count(*) from agent_runs where sim_run_id=%s and kind='agent'", (run,))
                ).fetchone()
            ) == (31,)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_events where run_id=%s and event_type='scenario.proactive_completed'",
                        (run,),
                    )
                ).fetchone()
            ) == (1,)
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            import json
            from unittest.mock import AsyncMock

            from app.api import map as map_api
            from tests.helpers import new_run

            await scenarios.save_result(conn, "mass_notifications", result)
            await conn.commit()
            stored = await (
                await conn.execute("select last_run_at,last_result from scenarios where id='mass_notifications'")
            ).fetchone()
            native_phases = {
                key: {"id": value["id"], "at": value["sim_time"].isoformat(), "payload": value["payload"]}
                for key, value in context.events.items()
            }
            native_ar = await (
                await conn.execute(
                    "select id,signal_id,outcome,total_tokens,prompt_tokens,completion_tokens,prompt_version,graph_version from agent_runs where id=%s",
                    (context.events["notified"]["payload"]["agent_run_id"],),
                )
            ).fetchone()
            steps = await (
                await conn.execute(
                    "select node,status,count(*) from agent_steps where run_id=%s group by node,status order by node,status",
                    (native_ar[0],),
                )
            ).fetchall()
            record_property(
                "native_phase_proof",
                json.dumps(
                    {
                        "run_id": run,
                        "fault_id": record.payload["fault_id"],
                        "basis": "synthetic5000metadata/no consent edits; Mock; native Sent emulated",
                        "phases": native_phases,
                        "counts": result["counts"],
                        "service_ar": list(native_ar),
                        "steps": steps,
                        "agent_ledger_count": 0,
                    },
                    ensure_ascii=False,
                ),
            )
            other = await new_run(conn, "historical map cannot borrow this run clock", kind="free")
            bomb = AsyncMock(side_effect=AssertionError("historical map не использует чужие часы"))
            monkeypatch.setattr(map_api, "get_map_zones", bomb)
            historical = await scenarios.evaluate(conn, scenarios.get("mass_notifications"), run)
            assert historical["passed"] is False
            assert historical["counts"]["map_basis"] == "historical_unavailable"
            assert any(
                check["code"] == "map_zone" and "not_verified" in check["detail"] for check in historical["checks"]
            )
            bomb.assert_not_awaited()
            await scenarios.save_result(conn, "mass_notifications", historical)
            await conn.commit()
            assert (
                await (
                    await conn.execute("select last_run_at,last_result from scenarios where id='mass_notifications'")
                ).fetchone()
                == stored
            )
            assert (await (await conn.execute("select current_run_id from sim_state where id=1")).fetchone()) == (
                other,
            )
            assert "completed" in (await case(conn, run)).events
    finally:
        await service.stop()
        await sim.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["good", "missing_checkpoint", "pending_human"])
async def test_paused_scripted_recovery_requires_exact_native_checkpoint_and_never_bypasses_human(
    mass_seeded, monkeypatch, boundary
):
    from app.agent import graph

    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim)
    original = graph.NODES["act"]
    entered = asyncio.Event()

    async def interrupted(state, deps):
        entered.set()
        await asyncio.Event().wait()
        return await original(state, deps)

    monkeypatch.setitem(graph.NODES, "act", interrupted)
    try:
        await service._proactive_cycle()
        await asyncio.wait_for(entered.wait(), timeout=10)
        await service.stop()
        monkeypatch.setitem(graph.NODES, "act", original)
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            ar = await (
                await conn.execute(
                    "select id,thread_id,signal_id,total_tokens from agent_runs where sim_run_id=%s", (run,)
                )
            ).fetchone()
            assert ar is not None
            assert (await (await conn.execute("select outcome from agent_runs where id=%s", (ar[0],))).fetchone()) == (
                None,
            )
            if boundary == "missing_checkpoint":
                await conn.execute("delete from langgraph.checkpoints where thread_id=%s", (ar[1],))
            elif boundary == "pending_human":
                await conn.execute(
                    "insert into human_decisions(sim_run_id,agent_run_id,signal_id,requested_sim,reason,agent_proposal,options,recommendation) values(%s,%s,%s,%s,'synthetic pending decision','{}','[]','manual')",
                    (run, ar[0], ar[2], sim.clock.sim_time),
                )
            await conn.commit()
        restarted = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim)
        await restarted._recover()  # paused обычный startup граф не запускает.
        await restarted._proactive_cycle()
        if restarted._inflight:
            await asyncio.gather(*list(restarted._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            assert (
                await (await conn.execute("select count(*) from agent_runs where sim_run_id=%s", (run,))).fetchone()
            ) == (1,)
            assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
            if boundary == "good":
                assert restarted.failed == 0
                assert (
                    await (await conn.execute("select outcome from agent_runs where id=%s", (ar[0],))).fetchone()
                ) == ("deferred",)
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from notifications where run_id=%s and template_code='proactive_fault' and status='sent'",
                            (run,),
                        )
                    ).fetchone()
                )[0] >= 90
            else:
                assert restarted.failed == 1
                assert (
                    await (await conn.execute("select outcome from agent_runs where id=%s", (ar[0],))).fetchone()
                ) == (None,)
                assert not await (await conn.execute("select 1 from notifications where run_id=%s", (run,))).fetchone()
                assert "failed" in (await case(conn, run)).events
                if boundary == "pending_human":
                    assert (
                        await (
                            await conn.execute(
                                "select count(*) from human_decisions where sim_run_id=%s and decision is null", (run,)
                            )
                        ).fetchone()
                    ) == (1,)
        await restarted.stop()
    finally:
        await service.stop()
        await sim.shutdown()


@pytest.mark.asyncio
async def test_unknown_delivery_keeps_phase_incomplete_and_never_retries_or_passes(mass_seeded, monkeypatch):
    from app.sim import scenarios

    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim)
    try:
        await service._proactive_cycle()
        await asyncio.gather(*list(service._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            await conn.execute(
                "update notifications set status='unknown',sent_sim=null,sent_at=null where run_id=%s and template_code='proactive_fault'",
                (run,),
            )
            await conn.commit()
            count = (
                await (await conn.execute("select count(*) from notifications where run_id=%s", (run,))).fetchone()
            )[0]
        for _ in range(3):
            await service._proactive_cycle()
            if service._inflight:
                await asyncio.gather(*list(service._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            context = await case(conn, run)
            assert set(context.events) == {"prepared"}
            result = await scenarios.evaluate(conn, scenarios.get("mass_notifications"), run)
            assert result["passed"] is False
            assert result["checks"][0]["ok"] is False
            assert result["counts"]["prevented_complaints"] is None
            assert (
                await (await conn.execute("select count(*) from notifications where run_id=%s", (run,))).fetchone()
            ) == (count,)
            assert (
                await (await conn.execute("select count(*) from agent_runs where sim_run_id=%s", (run,))).fetchone()
            ) == (1,)
            assert sim.clock.sim_time == context.initial_at
    finally:
        await service.stop()
        await sim.shutdown()


@pytest.mark.asyncio
async def test_scripted_public_clock_controls_fail_without_writes_stop_and_new_run_remain_available(
    mass_seeded, monkeypatch
):
    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    try:
        before_rng = sim.rng.dump_state()
        for action in ("resume", "step", "jump_to", "reset_day"):
            with pytest.raises(ValueError, match="Scripted-сценарий владеет часами"):
                await sim.control(action, minutes=1)
        with pytest.raises(ValueError, match="Scripted-сценарий владеет часами"):
            await sim.step(1)
        assert sim.clock.sim_time == record.at and sim.rng.dump_state() == before_rng
        assert sim.run_status == "paused"
        await sim.control("stop")
        assert sim.run_status == "stopped"
        await sim.control("start", label="ordinary new free run", start_paused=True)
        assert sim.run_id != run
        await sim.step(0.1)
        assert sim.stats["ticks"] == 1
    finally:
        await sim.shutdown()


@pytest.mark.asyncio
async def test_actual_early_customer_classification_fails_phase_before_next_owner_tick(mass_seeded, monkeypatch):
    from app.ingest.normalizer import create_signal, from_api_signal

    sim, run, record = await setup_case(mass_seeded, monkeypatch)
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(mass_seeded), sim=sim)
    try:
        await service._proactive_cycle()
        await asyncio.gather(*list(service._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            context = await case(conn, run)
            person = context.operations[-1]
            message = from_api_signal(
                {
                    "client_id": person["client_id"],
                    "channel_code": "chat",
                    "text": context.spec.complaint_templates[0].text,
                }
            )
            message["meta"].update(
                source_operation_id=person["operation_id"], source_fault_id=record.payload["fault_id"]
            )
            result = await create_signal(conn, message, source_code="api", run_id=run, sim_time=sim.clock.sim_time)
            await conn.commit()
        await service.submit(result["signal_id"])
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            # Owner ещё не делал следующий tick, но canonical classifier receipt
            # уже реальный. Его нельзя потерять между paused phase polls.
            assert (
                await (
                    await conn.execute(
                        "select count(first_complaint_sim) from behavior_runtime where run_id=%s", (run,)
                    )
                ).fetchone()
            ) == (0,)
        await service._proactive_cycle()
        if service._inflight:
            await asyncio.gather(*list(service._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            context = await case(conn, run)
            assert context.events["failed"]["payload"]["reason"] == "early_complaint"
            assert "notified" not in context.events and "complaints" not in context.events
            assert sim.clock.sim_time == context.initial_at
    finally:
        await service.stop()
        await sim.shutdown()


@pytest.mark.asyncio
async def test_ordinary_paused_free_run_checkpoint_is_not_automatic_scripted_recovery(seeded, monkeypatch):
    from unittest.mock import AsyncMock

    from app.agent import graph, runner
    from app.sim.engine import Simulator
    from tests.helpers import new_run, sim_now
    from tests.integration.test_proactive_fault import fault, operation

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "ordinary paused free remains manual", kind="free")
        await conn.execute("update sim_runs set status='paused' where id=%s", (run,))
        at = await sim_now(conn)
        person = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        fid = await fault(conn, run, at)
        await operation(conn, run, fid, person, at)
        await conn.commit()
    sim = Simulator(dsn=dsn(seeded))
    await sim.load_state()
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(seeded), sim=sim)
    original = graph.NODES["act"]
    entered = asyncio.Event()

    async def interrupted(state, deps):
        entered.set()
        await asyncio.Event().wait()
        return await original(state, deps)

    monkeypatch.setitem(graph.NODES, "act", interrupted)
    try:
        await service._proactive_cycle()
        await asyncio.wait_for(entered.wait(), timeout=10)
        await service.stop()
        monkeypatch.setitem(graph.NODES, "act", original)
        restart = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(seeded), sim=sim)
        bomb = AsyncMock(side_effect=AssertionError("ordinary paused не auto recovery"))
        monkeypatch.setattr(runner, "recover_agent_run", bomb)
        await restart._recover()
        await restart._proactive_cycle()
        if restart._inflight:
            await asyncio.gather(*list(restart._inflight))
        bomb.assert_not_awaited()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select ar.outcome,ar.interrupted_at is not null,exists(select 1 from langgraph.checkpoints c where c.thread_id=ar.thread_id) from agent_runs ar where ar.sim_run_id=%s",
                    (run,),
                )
            ).fetchall()
            assert rows == [(None, True, True)]
            assert not await (await conn.execute("select 1 from notifications where run_id=%s", (run,))).fetchone()
        await restart.stop()
    finally:
        await service.stop()
        await sim.shutdown()
