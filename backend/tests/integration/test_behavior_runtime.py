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


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "resume", "step", "jump_to", "reset_day"])
async def test_legacy_event_only_control_refuses_before_clock_counter_world_or_rng(seeded, monkeypatch, action):
    from app.sim.events import EventBus
    from app.sim.generators import CLIENT_ERROR_KINDS, CLIENT_ERROR_PRODUCT

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        monkeypatch.setattr(runtime, "configured_policy", lambda: None)
        now = await sim_now(conn)
        run = await new_run(conn, "T161 legacy pending-only", kind="free")
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        kind = next(iter(CLIENT_ERROR_KINDS))
        await EventBus(conn).emit(
            run,
            f"client_error.{kind}",
            {
                "client_id": client,
                "kind": kind,
                "product": CLIENT_ERROR_PRODUCT[kind],
                "operation_id": None,
                "details": {},
                "sim_time": now.isoformat(),
            },
            now,
        )
        await conn.execute("update sim_runs set status='paused' where id=%s", (run,))
        await conn.commit()
        sim = Simulator(dsn=seeded, behavior_policy=POLICY)
        await sim.load_state()
        memory = (
            sim.clock.sim_time,
            sim.clock.day_no,
            sim.rng.dump_state(),
            dict(sim.stats),
            sim.run_status,
            sim.clock.running,
        )
        before = await (
            await conn.execute(
                "select to_jsonb(st),r.status,r.resumed_count from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1"
            )
        ).fetchone()
        with pytest.raises(ValueError, match="Legacy run.*новый run"):
            await sim.control(action, **({"sim_time": now + dt.timedelta(hours=1)} if action == "jump_to" else {}))
        assert (
            sim.clock.sim_time,
            sim.clock.day_no,
            sim.rng.dump_state(),
            dict(sim.stats),
            sim.run_status,
            sim.clock.running,
        ) == memory
        assert sim.world is None
        after = await (
            await conn.execute(
                "select to_jsonb(st),r.status,r.resumed_count from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1"
            )
        ).fetchone()
        assert after == before
        assert (
            await (await conn.execute("select count(*) from behavior_runs where run_id=%s", (run,))).fetchone()
        ) == (0,)
        await sim.conn.close()


@pytest.mark.asyncio
async def test_legacy_graph_admission_refuses_before_agent_or_role_effects(seeded, monkeypatch):
    from app.agent.graph import process_signal
    from app.llm.base import LLMProfile
    from app.llm.failover import ProviderChain
    from app.llm.mock import MockProvider

    class NoCalls(MockProvider):
        async def complete_structured(self, *args, **kwargs):
            raise AssertionError("legacy graph не должен вызывать даже Mock provider")

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        monkeypatch.setattr(runtime, "configured_policy", lambda: None)
        now = await sim_now(conn)
        run = await new_run(conn, "T161 legacy graph", kind="free")
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        signal = (
            await (
                await conn.execute(
                    "insert into signals(run_id,client_id,channel_code,text,received_sim,origin) values(%s,%s,'chat','Историческая незавершённая жалоба',%s,'jury') returning id",
                    (run, client, now),
                )
            ).fetchone()
        )[0]
        await conn.commit()
        monkeypatch.setattr(runtime, "configured_policy", lambda: POLICY)
        profile = LLMProfile(code="mock", provider="mock", model="mock", role="main")
        with pytest.raises(ValueError, match="Legacy run.*новый run"):
            await process_signal(
                conn,
                signal_id=signal,
                chain=ProviderChain([NoCalls()], append_mock=False),
                profile=profile,
                sim_time=now,
            )
        assert (
            await (await conn.execute("select count(*) from agent_runs where sim_run_id=%s", (run,))).fetchone()
        ) == (0,)
        assert (await (await conn.execute("select status from signals where id=%s", (signal,))).fetchone()) == ("new",)
        await conn.rollback()


@pytest.mark.asyncio
async def test_owned_reset_day_processes_timers_and_preserves_working_deadline(seeded, monkeypatch):
    from app.sim.clock import MSK, is_working_time

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, _, sim = await setup(conn, monkeypatch, seeded)
        friday = dt.datetime(2026, 11, 6, 23, 55, tzinfo=MSK)
        sim.clock.sim_time = friday
        sim.clock.day_no = 10
        await sim.persist()
        await sim.conn.commit()
        await failed(conn, run, client, friday)
        world = await sim._ensure_world()
        person = next(item for item in world.clients if item.id == client)
        person.channel_weights = {"chat": 1.0}
        due = friday + dt.timedelta(minutes=3)
        world.pending.append(
            PendingSignal(due, person, "client_error", "deposit", None, None, None, None, uuid.uuid4())
        )
        await sim.step(1)
        patience = (
            await (
                await conn.execute("select patience_due_sim from behavior_runtime where run_id=%s", (run,))
            ).fetchone()
        )[0]
        assert is_working_time(patience) and patience > friday + dt.timedelta(days=2)
        await conn.rollback()
        await sim.control("reset_day")
        assert sim.clock.sim_time == dt.datetime(2026, 11, 7, 9, tzinfo=MSK)
        assert sim.clock.day_no == 11 and not sim.clock.running
        assert sim.stats["ticks"] > 1 and world.pending == []
        assert (
            await (
                await conn.execute(
                    "select count(*) from signals s join ingest_messages m on m.signal_id=s.id where s.run_id=%s and m.source_code='sim_generator' and s.received_sim=%s",
                    (run, due),
                )
            ).fetchone()
        ) == (1,)
        assert (
            await (
                await conn.execute("select patience_due_sim from behavior_runtime where run_id=%s", (run,))
            ).fetchone()
        ) == (patience,)
        assert (
            await (
                await conn.execute(
                    "select status,due_sim from behavior_work where run_id=%s and kind='patience'", (run,)
                )
            ).fetchone()
        ) == ("pending", patience)
        assert (
            await (await conn.execute("select sim_time,day_no,rng_state from sim_state where id=1")).fetchone()
        ) == (sim.clock.sim_time, 11, sim.rng.dump_state())
        await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("identified", [True, False])
async def test_live_graph_and_clock_keep_owned_state_hazard_and_rng_unchanged(seeded, monkeypatch, identified):
    from tests.helpers import run_agent_on

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        owned, client, now, sim = await setup(conn, monkeypatch, seeded)
        await failed(conn, owned, client, now)
        await sim.step(1)
        before = await (
            await conn.execute(
                "select to_jsonb(cs),to_jsonb(b) from client_states cs join behavior_runtime b on b.state_id=cs.id where b.run_id=%s",
                (owned,),
            )
        ).fetchone()
        assert before is not None
        rng = sim.rng.dump_state()
        risk = (await (await conn.execute("select churn_risk from clients where id=%s", (client,))).fetchone())[0]
        live = await new_run(conn, "T161 actual live input", kind="live")
        await sim.conn.close()
        active = Simulator(dsn=seeded)
        await active.load_state()
        assert active.behavior_policy is not None
        active.full_execution = True
        monkeypatch.setattr(active, "_start_loop", lambda: setattr(active.clock, "running", True))
        active._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
        _, result = await run_agent_on(
            conn,
            "Не могу открыть вклад в приложении, ошибка DEP-TIMEOUT-503. Прошу помочь.",
            client_id=client if identified else None,
            run_id=live,
        )
        await conn.commit()
        assert result["outcome"] in ("completed", "deferred", "awaiting_human", "fallback_mock"), result.get("errors")
        assert active.rng.dump_state() == rng
        await active._ensure_world()
        # Штатный TeamEmulator.load закрепляет план своими draw. После load
        # admission и часы live не должны добавлять behavior hazard draws.
        clock_rng = active.rng.dump_state()
        await active.control("pause")
        await active.control("resume")
        await active.control("pause")
        await active.control("step", step_minutes=15)
        assert active.world.behavior_policy is None
        assert active.rng.dump_state() == clock_rng
        assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone()) == (clock_rng,)
        assert (
            await (
                await conn.execute(
                    "select to_jsonb(cs),to_jsonb(b) from client_states cs join behavior_runtime b on b.state_id=cs.id where b.run_id=%s",
                    (owned,),
                )
            ).fetchone()
            == before
        )
        assert (await (await conn.execute("select churn_risk from clients where id=%s", (client,))).fetchone()) == (
            risk,
        )
        assert (
            await (
                await conn.execute(
                    "select (select count(*) from behavior_runs where run_id=%s),"
                    "(select count(*) from behavior_evidence where run_id=%s),"
                    "(select count(*) from behavior_runtime where run_id=%s)",
                    (live, live, live),
                )
            ).fetchone()
        ) == (0, 0, 0)
        await active.conn.close()
