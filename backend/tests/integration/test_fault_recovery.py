"""T-161/T031: native schedule/correlation/impact без RAM defaults и RNG draw."""

from __future__ import annotations

import copy
import datetime as dt
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.sim.engine import Simulator
from app.sim.events import EventBus
from app.sim.fault_recovery import FaultScheduleError, load_faults
from app.sim.generators import World
from app.sim.rng import SimRng
from app.sim.teams import PendingRegression, TeamEmulator
from tests.helpers import dsn, new_run

from .test_behavior_runtime import declared_fault, setup


@pytest.mark.asyncio
async def test_generated_faults_reload_exact_schedule_correlation_impact_and_rng(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, _, sim = await setup(conn, monkeypatch, seeded)
        sim._intensities.update(fault=240, op=6000)
        await sim.step(1)
        assert sim.world.active_faults
        sim.world.intensities["fault"] = 0
        for _ in range(5):
            await sim.step(1)
            if any(item["impact"] for item in sim.world.active_faults):
                break
        assert any(item["impact"] for item in sim.world.active_faults)
        expected, state = copy.deepcopy(sim.world.active_faults), sim.rng.dump_state()
        await sim.conn.close()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as restarted:
            rng = SimRng(999)
            rng.load_state(state)
            restored = World(restarted, EventBus(restarted), rng, run)
            await restored.load()
            assert restored.active_faults == expected
            assert rng.dump_state() == state
            assert await load_faults(restarted, run) == expected
        assert (
            await (
                await conn.execute(
                    "select count(*) from operations where run_id=%s and status='failed' and fault_id is not null",
                    (run,),
                )
            ).fetchone()
        )[0] == sum(item["impact"] for item in expected)


@pytest.mark.asyncio
async def test_real_regression_producer_persists_existing_duration_and_native_correlation(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, started, sim = await setup(conn, monkeypatch, seeded)
        await sim.step(120)
        now = sim.clock.sim_time
        incident = (
            await (
                await conn.execute(
                    "insert into incidents(run_id,title,incident_type,product_code,team_code,system_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) "
                    "values(%s,'native regression schedule','tech_fault','deposit','team_deposits','sub_deposits','medium','high',2,'fix_deployed','scenario',%s,%s,%s) returning id",
                    (run, started, started + dt.timedelta(days=1), started + dt.timedelta(hours=1)),
                )
            ).fetchone()
        )[0]
        release_at = now - dt.timedelta(minutes=60)
        release = (
            await (
                await conn.execute(
                    "insert into team_actions(run_id,incident_id,team_code,action,payload,action_sim) values(%s,%s,'team_deposits','release','{}',%s) returning id",
                    (run, incident, release_at),
                )
            ).fetchone()
        )[0]
        rng = SimRng(42)
        emulator = TeamEmulator(rng, conn, EventBus(conn), run)
        await emulator.load()
        emulator.pending_regressions = [
            PendingRegression(
                incident, release, release_at, 60, "DEP-TIMEOUT-503", "sub_deposits", "deposit", "sub_deposits"
            )
        ]
        world = SimpleNamespace(active_faults=[])
        state = rng.dump_state()
        await emulator._process_regressions(now, world)
        assert len(world.active_faults) == 1
        assert rng.dump_state() == state
        expected = copy.deepcopy(world.active_faults)
        event = await (
            await conn.execute(
                "select payload,correlation_id from sim_events where run_id=%s and event_type='fault.regression'",
                (run,),
            )
        ).fetchone()
        assert event[0]["expected_duration_min"] == 90
        assert expected[0]["corr"] == event[1] and expected[0]["expected_end"] == now + dt.timedelta(minutes=90)
        await conn.commit()
        assert await load_faults(conn, run) == expected
        await emulator._process_regressions(now, world)
        assert len(world.active_faults) == 1
        await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["missing", "duration", "boolean", "duplicate", "time", "system", "foreign", "future", "family"]
)
async def test_invalid_schedule_refuses_before_rng_time_or_data_effects(seeded, monkeypatch, bad):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        foreign = await new_run(conn, "foreign schedule", kind="free")
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        started = now + dt.timedelta(minutes=1) if bad == "future" else now
        fault = (
            await (
                await conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s) returning id",
                    (run, started),
                )
            ).fetchone()
        )[0]
        payload = {
            "event_type": "fault.started",
            "fault_id": fault,
            "system": "sub_deposits",
            "error_code": "DEP-TIMEOUT-503",
            "started_sim": started.isoformat(),
            "expected_duration_min": 90,
        }
        if bad == "duration":
            payload.pop("expected_duration_min")
        if bad == "boolean":
            payload["expected_duration_min"] = True
        if bad == "time":
            payload["started_sim"] = (now - dt.timedelta(minutes=1)).isoformat()
        if bad == "system":
            payload["system"] = "core_processing"
        if bad == "family":
            payload["event_type"] = "fault.resolved"
        if bad != "missing":
            for _ in range(2 if bad == "duplicate" else 1):
                await conn.execute(
                    "insert into sim_events(run_id,event_type,payload,sim_time) values(%s,'fault.started',%s,%s)",
                    (foreign if bad == "foreign" else run, Jsonb(payload), started),
                )
        await conn.commit()
        before = await (
            await conn.execute(
                "select to_jsonb(f),s.sim_time,s.rng_state,r.status,r.public_id from faults f join sim_runs r on r.id=f.run_id cross join sim_state s where f.id=%s and s.id=1",
                (fault,),
            )
        ).fetchone()
        memory = (sim.clock.sim_time, sim.rng.dump_state(), dict(sim.stats))
        with pytest.raises(FaultScheduleError) as err:
            await sim.step(1)
        assert err.value.run_public_id == before[4] and err.value.fault_id == fault
        assert "данные сохранены" in str(err.value)
        assert (sim.clock.sim_time, sim.rng.dump_state(), sim.stats) == memory
        assert (
            await (
                await conn.execute(
                    "select to_jsonb(f),s.sim_time,s.rng_state,r.status,r.public_id from faults f join sim_runs r on r.id=f.run_id cross join sim_state s where f.id=%s and s.id=1",
                    (fault,),
                )
            ).fetchone()
            == before
        )
        assert (await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        await sim.conn.close()


@pytest.mark.asyncio
async def test_explicit_new_run_recovers_without_editing_unknown_legacy_fault(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        await conn.execute(
            "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s)",
            (run, now),
        )
        await conn.commit()
        old = await (await conn.execute("select to_jsonb(f) from faults f where run_id=%s", (run,))).fetchone()
        with pytest.raises(FaultScheduleError, match="fault_schedule_missing"):
            await sim.step(1)
        await sim.control("start", label="explicit operator recovery", start_paused=True)
        assert sim.run_id != run
        await sim.step(1)
        assert await (await conn.execute("select to_jsonb(f) from faults f where run_id=%s", (run,))).fetchone() == old
        assert (
            await (
                await conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='fault.started'", (run,)
                )
            ).fetchone()
        ) == (0,)
        await sim.conn.close()


@pytest.mark.asyncio
async def test_live_fault_recovers_native_schedule_without_enabling_hazard(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        _, _, now, first = await setup(conn, monkeypatch, seeded)
        await first.conn.close()
        run = await new_run(conn, "native live schedule", kind="live")
        fault = await declared_fault(conn, run, now, duration_min=30)
        await conn.commit()
        sim = Simulator(dsn=seeded)
        await sim.load_state()
        assert sim.behavior_policy is not None
        sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0)
        rng = sim.rng.dump_state()
        await sim.step(1)
        assert sim.world.behavior_policy is None and sim.rng.dump_state() == rng
        expected = copy.deepcopy(sim.world.active_faults)
        assert expected[0]["id"] == fault and expected[0]["expected_end"] == now + dt.timedelta(minutes=30)
        await sim.conn.close()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as restarted:
            restored_rng = SimRng(999)
            restored_rng.load_state(rng)
            world = World(restarted, EventBus(restarted), restored_rng, run)
            await world.load()
            assert world.active_faults == expected and restored_rng.dump_state() == rng
            assert (
                await (
                    await restarted.execute("select count(*) from behavior_runtime where run_id=%s", (run,))
                ).fetchone()
            ) == (0,)
            assert (
                await (
                    await restarted.execute("select count(*) from behavior_evidence where run_id=%s", (run,))
                ).fetchone()
            ) == (0,)


@pytest.mark.asyncio
async def test_noncurrent_active_fault_never_uses_foreign_clock(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        fault = await declared_fault(conn, run, now)
        await conn.commit()
        other = await new_run(conn, "different current clock", kind="free")
        assert other != run
        before = await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone()
        with pytest.raises(FaultScheduleError) as err:
            await load_faults(conn, run)
        assert err.value.code == "fault_clock_not_current" and err.value.fault_id == fault
        assert await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone() == before
        await sim.conn.close()
