"""Команда внутри native tick не использует ещё не записанные будущие часы."""

import datetime as dt
import math

import psycopg
import pytest

from app.agent import proactive
from app.agent.graph import process_signal
from app.economics import dcltv
from app.sim.engine import Simulator
from app.sim.events import EventBus
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now
from tests.integration.test_proactive_fault import fault, operation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "late_impact", ["none", "before_take", "after_take", "future_operation", "corrupt_counter", "future_clock"]
)
async def test_native_tick_team_economics_stays_within_its_transaction_clock(seeded, monkeypatch, late_impact):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "tick effect clock")
        at = await sim_now(conn)
        person = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        await conn.execute(
            "update clients set consents=jsonb_build_object('proactive',true),contacts=contacts||jsonb_build_object('preferred','chat') where id=%s",
            (person,),
        )
        fid = await fault(conn, run, at, emit=False)
        await EventBus(conn).emit(
            run,
            "fault.started",
            {
                "fault_id": fid,
                "system": "notification_gw",
                "error_code": "NOTIF-DELAY",
                "started_sim": at.isoformat(),
                "expected_duration_min": 480,
                "impact_count": 0,
                "affected_clients": 0,
            },
            at,
        )
        await operation(conn, run, fid, person, at)
        [signal] = await proactive.produce(conn)
        await conn.commit()
        state = await process_signal(conn, signal_id=signal, chain=mock_chain(), profile=MOCK_PROFILE)
        assert state["outcome"] == "deferred"
        incident = (await (await conn.execute("select id from incidents where run_id=%s", (run,))).fetchone())[0]
        # Positive control: producer lineage/cohort валидны ДО продвижения tick.
        economics = await dcltv.compute_incident(conn, incident, sim_time=at)
        assert economics["affected_count"] == 1
        await conn.commit()

    observed = []
    original = dcltv.compute_incident

    async def measured(connection, incident_id, *, sim_time=None):
        own_clock = (
            await (
                await connection.execute("select sim_time from sim_state where id=1 and current_run_id=%s", (run,))
            ).fetchone()
        )[0]
        observed.append((sim_time, own_clock))
        return await original(connection, incident_id, sim_time=sim_time)

    monkeypatch.setattr(dcltv, "compute_incident", measured)
    sim = Simulator(dsn=seeded)
    await sim.load_state()
    sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
    try:
        world = await sim._ensure_world()
        await world.team_emulator.tick(at, world)
        take_at = next(step.at for step in world.team_emulator.plans[incident].steps if step.action == "take")
        offset = 15 if ((take_at - at).total_seconds() - 900) % 3600 else 16
        first = at + dt.timedelta(minutes=offset)
        window_end = first + dt.timedelta(hours=max(0, math.ceil((take_at - first).total_seconds() / 3600)))
        assert window_end > take_at
        if late_impact in ("before_take", "after_take", "future_operation"):
            second = (await (await sim.conn.execute("select id from clients order by id offset 1 limit 1")).fetchone())[
                0
            ]
            happened = (
                at + dt.timedelta(minutes=1) if late_impact == "before_take" else take_at + (window_end - take_at) / 2
            )
            if late_impact == "future_operation":
                happened = window_end + dt.timedelta(days=1)
            await operation(sim.conn, run, fid, second, happened)
        if late_impact == "corrupt_counter":
            await sim.conn.execute("update incidents set mass_impact=999 where id=%s", (incident,))
        await sim.persist()
        await sim.conn.commit()
        before_economics = (
            await (
                await sim.conn.execute("select to_jsonb(e) from incident_economics e where incident_id=%s", (incident,))
            ).fetchone()
        )[0]
        await sim.conn.commit()
        if late_impact == "corrupt_counter":
            with pytest.raises(ValueError, match="cohort/mass"):
                await sim.step(offset)
            assert sim.clock.sim_time == at
            assert (
                await (await sim.conn.execute("select mass_impact from incidents where id=%s", (incident,))).fetchone()
            )[0] == 999
            assert (
                await (
                    await sim.conn.execute(
                        "select to_jsonb(e) from incident_economics e where incident_id=%s", (incident,)
                    )
                ).fetchone()
            )[0] == before_economics
            return
        if late_impact == "future_clock":
            from app.agent.incident_observation import observe_incident_economics
            from app.agent.tools.base import ToolContext

            forged = ToolContext(
                sim.conn, run_id=run, agent_run_id=0, sim_time=at, economics_time=at + dt.timedelta(days=1)
            )
            with pytest.raises(ValueError, match="fault_monitor economics"):
                await observe_incident_economics(forged, incident)
            assert (
                await (
                    await sim.conn.execute(
                        "select to_jsonb(e) from incident_economics e where incident_id=%s", (incident,)
                    )
                ).fetchone()
            )[0] == before_economics
            return
        for index in range(9):
            await sim.step(offset if index == 0 else 60)
            took = await (
                await sim.conn.execute(
                    "select action_sim from team_actions where run_id=%s and incident_id=%s and action='take'",
                    (run, incident),
                )
            ).fetchone()
            await sim.conn.commit()
            if took:
                break
        else:
            pytest.fail("native team take не выполнен за8сим-часов")
        assert took[0] == take_at
        assert observed and all(requested <= committed for requested, committed in observed)
        value = await (
            await sim.conn.execute(
                "select computed_sim,affected_count from incident_economics where incident_id=%s", (incident,)
            )
        ).fetchone()
        expected = 2 if late_impact in ("before_take", "after_take") else 1
        assert value[0] == sim.clock.sim_time and value[1] == expected
    finally:
        await sim.conn.close()


@pytest.mark.asyncio
async def test_tick_clock_is_private_until_commit_and_rolls_back_with_effects(seeded, monkeypatch):
    from tests.integration.test_behavior_runtime import setup

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, at, sim = await setup(conn, monkeypatch, seeded)
    world = await sim._ensure_world()
    await sim.conn.commit()
    memory_rng, memory_stats = sim.rng.dump_state(), dict(sim.stats)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as observer:
        before = await (
            await observer.execute(
                "select sim_time,rng_state,(select count(*) from sim_events where run_id=%s) from sim_state where id=1",
                (run,),
            )
        ).fetchone()

        async def fail_after_clock(when, _world):
            private = (await (await sim.conn.execute("select sim_time from sim_state where id=1")).fetchone())[0]
            public = (await (await observer.execute("select sim_time from sim_state where id=1")).fetchone())[0]
            assert private == when == at + dt.timedelta(minutes=15)
            assert public == at
            raise RuntimeError("injected_tick_effect_failure")

        monkeypatch.setattr(world.team_emulator, "tick", fail_after_clock)
        try:
            with pytest.raises(RuntimeError, match="injected_tick_effect_failure"):
                await sim.step(15)
            after = await (
                await observer.execute(
                    "select sim_time,rng_state,(select count(*) from sim_events where run_id=%s) from sim_state where id=1",
                    (run,),
                )
            ).fetchone()
            assert after == before
            assert sim.clock.sim_time == at
            assert sim.rng.dump_state() == memory_rng
            assert sim.stats == memory_stats
        finally:
            await sim.conn.close()
