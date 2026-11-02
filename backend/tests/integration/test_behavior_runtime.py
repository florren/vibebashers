"""T-161 actual0017: Sim tick owner, durable timers, recovery и preflight."""

from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.sim.behavior import runtime
from app.sim.engine import Simulator
from app.sim.generators import PendingSignal
from app.sim.rng import SimRng
from tests.helpers import dsn, new_run, sim_now

from .test_behavior_owner import POLICY


async def setup(conn, monkeypatch, url):
    # Явный candidate injection для isolated proof. Tracked enabled=false пока
    # остаётся до полного cohesive runtime proof; новые values не добавляются.
    monkeypatch.setattr(runtime, "configured_policy", lambda: POLICY)
    now = await sim_now(conn)
    run = await new_run(conn, "T161 actual runtime", kind="free")
    await conn.execute(
        "update sim_state set seed=1,rng_state=%s,running=false where id=1",
        (Jsonb(SimRng(1).dump_state()),),
    )
    await conn.execute("update sim_runs set seed=1 where id=%s", (run,))
    client = (
        await (
            await conn.execute(
                "select id from clients where psychotype_code='anxious' and segment_code='mass' order by id limit 1"
            )
        ).fetchone()
    )[0]
    await conn.commit()
    sim = Simulator(dsn=url, behavior_policy=POLICY)
    await sim.load_state()
    sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
    return run, client, now, sim


async def failed(conn, run, client, now):
    fault = (
        await (
            await conn.execute(
                "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s) returning id",
                (run, now),
            )
        ).fetchone()
    )[0]
    op = (
        await (
            await conn.execute(
                "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) values(%s,%s,'deposit','deposit_open',ARRAY['sub_deposits'],'failed','DEP-TIMEOUT-503',%s,%s) returning id",
                (run, client, fault, now),
            )
        ).fetchone()
    )[0]
    await conn.commit()
    return fault, op


@pytest.mark.asyncio
async def test_tick_creates_single_episode_and_restart_consumes_durable_complaint(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        _, op = await failed(conn, run, client, now)
        await sim.step(1)
        assert sim.world.pending == []
        due = (
            await (
                await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
            ).fetchone()
        )[0]
        assert (
            await (await conn.execute("select count(*) from behavior_runtime where run_id=%s", (run,))).fetchone()
        ) == (1,)
        await conn.rollback()
        await sim.conn.close()
        restored = Simulator(dsn=seeded, behavior_policy=POLICY)
        await restored.load_state()
        restored._intensities = dict(sim._intensities)
        before = restored.rng.dump_state()
        assert restored.clock.sim_time == now + dt.timedelta(minutes=1)
        assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()) == (0,)
        await conn.rollback()
        await restored.step((due - restored.clock.sim_time).total_seconds() / 60)
        signal = await (
            await conn.execute(
                "select s.received_sim,s.source_operation_id,s.classification,m.source_code from signals s join ingest_messages m on m.signal_id=s.id where s.run_id=%s",
                (run,),
            )
        ).fetchone()
        assert signal[0] == due and signal[1] == op and signal[2] is None
        assert signal[3] == "behavior_param"
        assert restored.rng.dump_state() != before
        assert restored.world.pending == []
        await conn.rollback()
        count = (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone())[0]
        await conn.rollback()
        await restored.step(0.01)
        assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone())[
            0
        ] == count
        await restored.conn.close()


@pytest.mark.asyncio
async def test_world_timer_is_durable_and_uses_normalizer_without_gold(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        world = await sim._ensure_world()
        person = next(item for item in world.clients if item.id == client)
        person.channel_weights = {"chat": 1.0}
        due = now + dt.timedelta(minutes=10)
        world.pending.append(
            PendingSignal(due, person, "client_error", "deposit", None, None, None, None, uuid.uuid4())
        )
        await sim.step(1)
        assert world.pending == []
        assert (
            await (
                await conn.execute(
                    "select count(*) from behavior_pending_signals where run_id=%s and consumed_sim is null", (run,)
                )
            ).fetchone()
        ) == (1,)
        await conn.rollback()
        await sim.conn.close()
        restored = Simulator(dsn=seeded, behavior_policy=POLICY)
        await restored.load_state()
        restored._intensities = dict(sim._intensities)
        await restored.step(9)
        row = await (
            await conn.execute(
                "select s.received_sim,s.classification,s.meta,m.source_code from signals s join ingest_messages m on m.signal_id=s.id where s.run_id=%s",
                (run,),
            )
        ).fetchone()
        assert row[0] == due and row[1] is None and row[3] == "sim_generator"
        assert "gold" not in row[2] and "generator_hint" not in row[2]
        assert (
            await (
                await conn.execute(
                    "select count(*) from behavior_pending_signals where run_id=%s and consumed_sim is not null", (run,)
                )
            ).fetchone()
        ) == (1,)
        await restored.conn.close()


@pytest.mark.asyncio
async def test_legacy_nonempty_preflight_has_no_time_rng_world_or_db_effects(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        monkeypatch.setattr(runtime, "configured_policy", lambda: None)
        now = await sim_now(conn)
        run = await new_run(conn, "T161 legacy", kind="free")
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        await failed(conn, run, client, now)
        sim = Simulator(dsn=seeded, behavior_policy=POLICY)
        await sim.load_state()
        before = (sim.clock.sim_time, sim.clock.day_no, sim.rng.dump_state(), dict(sim.stats))
        assert sim.world is None
        with pytest.raises(ValueError, match="Legacy run.*новый run"):
            await sim.step(5)
        assert (sim.clock.sim_time, sim.clock.day_no, sim.rng.dump_state(), dict(sim.stats)) == before
        assert sim.world is None
        assert (
            await (await conn.execute("select count(*) from behavior_runs where run_id=%s", (run,))).fetchone()
        ) == (0,)
        assert (
            await (await conn.execute("select count(*) from behavior_evidence where run_id=%s", (run,))).fetchone()
        ) == (0,)
        await sim.conn.close()


@pytest.mark.asyncio
async def test_fresh_marker_and_tick_rollback_retry_are_atomic(seeded, monkeypatch):
    from app.sim.behavior.owner import BehaviorOwner

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await conn.execute("delete from behavior_runs where run_id=%s", (run,))
        await conn.commit()
        before = (sim.clock.sim_time, sim.rng.dump_state(), dict(sim.stats))
        advance = BehaviorOwner.advance

        async def broken(self, **kwargs):
            await advance(self, **kwargs)
            raise RuntimeError("injected tick failure")

        monkeypatch.setattr(BehaviorOwner, "advance", broken)
        with pytest.raises(RuntimeError, match="injected tick failure"):
            await sim.step(1)
        assert (sim.clock.sim_time, sim.rng.dump_state(), dict(sim.stats)) == before
        assert (
            await (await conn.execute("select count(*) from behavior_runs where run_id=%s", (run,))).fetchone()
        ) == (0,)
        await conn.rollback()
        monkeypatch.setattr(BehaviorOwner, "advance", advance)
        await sim.step(1)
        assert (
            await (await conn.execute("select count(*) from behavior_runs where run_id=%s", (run,))).fetchone()
        ) == (1,)
        assert sim.clock.sim_time == now + dt.timedelta(minutes=1)
        await sim.conn.close()


@pytest.mark.asyncio
async def test_real_world_failed_operations_use_one_owner_without_legacy_complaints(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        await conn.execute(
            "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s)",
            (run, now),
        )
        await conn.commit()
        world = await sim._ensure_world()
        person = next(item for item in world.clients if item.psychotype == "anxious" and "deposit" in item.products)
        person.products = ["deposit"]
        world.clients = [person]
        world.scale = 1
        world.intensities["op"] = 120
        await sim.step(60)
        failed = (
            await (
                await conn.execute("select count(*) from operations where run_id=%s and status='failed'", (run,))
            ).fetchone()
        )[0]
        assert failed > 1 and world.pending == []
        assert (
            await (
                await conn.execute(
                    "select count(*) from behavior_evidence where run_id=%s and source_kind='operation' and consumed_sim is not null",
                    (run,),
                )
            ).fetchone()
        ) == (failed,)
        assert (
            await (await conn.execute("select count(*) from behavior_runtime where run_id=%s", (run,))).fetchone()
        ) == (1,)
        assert (
            await (
                await conn.execute("select count(*) from behavior_work where run_id=%s and kind='complaint'", (run,))
            ).fetchone()
        ) == (1,)
        assert (
            await (
                await conn.execute("select count(*) from behavior_pending_signals where run_id=%s", (run,))
            ).fetchone()
        ) == (0,)
        assert (
            await (
                await conn.execute(
                    "select count(*) from signals s join ingest_messages m on m.signal_id=s.id where s.run_id=%s and m.source_code<>'behavior_param'",
                    (run,),
                )
            ).fetchone()
        ) == (0,)
        assert (await (await conn.execute("select count(*) from external_posts where run_id=%s", (run,))).fetchone())[
            0
        ] == (
            await (
                await conn.execute(
                    "select count(*) from signals where run_id=%s and channel_code in ('social','review_portal')",
                    (run,),
                )
            ).fetchone()
        )[0]
        await sim.conn.close()
