"""Собственный PG: reconnect не переигрывает неизвестный COMMIT и ручной intent."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from app.sim import engine, runs
from app.sim.engine import Simulator, StaleSimulatorError
from app.sim.generators import PendingSignal, World
from app.sim.rng import SimRng
from app.sim.teams import _plan_blob
from tests.helpers import dsn

pytestmark = pytest.mark.integration


async def bank(url):
    async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
        tables = await (
            await conn.execute(
                "select schemaname,tablename from pg_tables where schemaname in "
                "('public','langgraph','llm_runtime','channel_runtime') order by 1,2"
            )
        ).fetchall()
        return {
            (schema, name): await (
                await conn.execute(
                    sql.SQL(
                        "select count(*),md5(coalesce(string_agg(md5(to_jsonb(t)::text),'' "
                        "order by md5(to_jsonb(t)::text)),'')) from {}.{} t"
                    ).format(sql.Identifier(schema), sql.Identifier(name))
                )
            ).fetchone()
            for schema, name in tables
        }


async def running(seeded, monkeypatch, *, legacy=True):
    if legacy:
        monkeypatch.setattr(engine, "configured_policy", lambda: None)
    sim = Simulator(dsn=seeded)
    original_start = sim._start_loop
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    sim._intensities = {"op": 4000, "fault": 0, "client_error": 0, "signal_noise": 0}
    await sim.control("start", label="OWN network recovery", start_paused=True)
    await sim.control("resume")
    if sim.behavior_policy is not None:
        from app.sim.behavior.runtime import prepare_run

        await sim.conn.execute("select 1")
        await prepare_run(sim.conn, sim.run_id, sim.clock.sim_time, sim.behavior_policy)
    world = await sim._ensure_world()
    await sim.persist()
    await sim.conn.commit()
    monkeypatch.setattr(sim, "_start_loop", original_start)
    # Один tick ровно на минуту: стабильный fixed-seed batch с native операциями.
    monkeypatch.setattr(engine, "REAL_TICK_S", 1)
    sim.clock.speed = 60
    await sim.persist()
    await sim.conn.commit()
    return sim, world


async def stop(sim):
    await sim._stop_loop()
    if sim.conn is not None:
        await sim.conn.close()


def connection_gate(monkeypatch, entered, online, *, blocked=False, auth=False):
    original = psycopg.AsyncConnection.connect
    attempts = []

    async def connect(cls, *args, **kwargs):
        if kwargs.get("connect_timeout") == 3:
            attempts.append(kwargs)
            entered.set()
            if blocked:
                await online.wait()
            if auth:
                raise psycopg.errors.InvalidPassword("synthetic auth refusal")
            if not online.is_set():
                raise psycopg.errors.CannotConnectNow("synthetic PG recovering")
        return await original(*args, **kwargs)

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", classmethod(connect))
    return attempts


def disconnect_first_native_batch(monkeypatch, disconnected, url):
    original = World.gen_operations
    first = True

    async def generate(world, at, minutes):
        nonlocal first
        count = await original(world, at, minutes)
        if first:
            first = False
            assert count > 0
            async with await psycopg.AsyncConnection.connect(dsn(url)) as killer:
                await killer.execute("select pg_terminate_backend(%s)", (world.conn.info.backend_pid,))
            # Следующий настоящий запрос получает AdminShutdown/закрытый transport.
            disconnected.set()
            await world.conn.execute("select 1")
            raise AssertionError("terminated native connection accepted query")
        return count

    monkeypatch.setattr(World, "gen_operations", generate)


@pytest.mark.parametrize("legacy", [True, False])
async def test_confirmed_pre_reconnect_preserves_full_bank_rng_and_native_pending(seeded, monkeypatch, legacy):
    sim, world = await running(seeded, monkeypatch, legacy=legacy)
    rid, before_point = sim.run_id, sim._tick_point()
    expected_plan = None
    pending = None
    if legacy:
        now = sim.clock.sim_time
        iid = (
            await (
                await sim.conn.execute(
                    "insert into incidents(run_id,title,incident_type,product_code,team_code,system_code,complexity,"
                    "criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) "
                    "values(%s,'native network plan','tech_fault','deposit','team_deposits','sub_deposits',"
                    "'medium','high',2,'routed','scenario',%s,%s,%s) returning id",
                    (rid, now, now + dt.timedelta(days=3), now + dt.timedelta(hours=4)),
                )
            ).fetchone()
        )[0]
        await world.team_emulator.tick(now, world)
        expected_plan = (iid, _plan_blob(world.team_emulator.plans[iid]))
        pending = PendingSignal(
            now + dt.timedelta(seconds=30),
            world.by_product["deposit"][0],
            "client_error",
            "deposit",
            None,
            None,
            None,
            None,
            uuid.uuid4(),
        )
        world.pending = [copy.deepcopy(pending)]
        await sim.persist()
        await sim.conn.commit()
        before_point = sim._tick_point()
    before_bank = await bank(seeded)
    disconnected, entered, online, recovered, release, tick_done = (asyncio.Event() for _ in range(6))
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    attempts = connection_gate(monkeypatch, entered, online)
    original_reconnect, original_publish = sim._reconnect_running_tick, sim._publish_tick

    async def reconnect(tick, error):
        await original_reconnect(tick, error)
        assert sim._tick_point() == before_point and sim.run_id == rid
        assert await bank(seeded) == before_bank  # Reconnect — только readonly.
        loaded = await sim._ensure_world()
        if legacy:
            assert loaded.pending == [pending]
            assert _plan_blob(loaded.team_emulator.plans[expected_plan[0]]) == expected_plan[1]
        assert sim._tick_point() == before_point  # Native load не делает RNG draw.
        await sim.conn.rollback()
        recovered.set()
        await release.wait()

    async def published():
        await original_publish()
        if sim.stats["ticks"]:
            tick_done.set()

    monkeypatch.setattr(sim, "_reconnect_running_tick", reconnect)
    monkeypatch.setattr(sim, "_publish_tick", published)
    sim._start_loop()
    try:
        await asyncio.wait_for(entered.wait(), 8)
        assert disconnected.is_set() and not recovered.is_set()
        assert await bank(seeded) == before_bank
        online.set()
        await asyncio.wait_for(recovered.wait(), 8)
        assert attempts and all(a["connect_timeout"] == 3 for a in attempts)
        release.set()
        await asyncio.wait_for(tick_done.wait(), 8)
        await sim.control("pause")
        assert sim.run_id == rid and sim.stats["ticks"] == 1 and sim.stats["ops"] > 0
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            state = await (
                await conn.execute("select current_run_id,sim_time,rng_state from sim_state where id=1")
            ).fetchone()
            assert state == (rid, sim.clock.sim_time, sim.rng.dump_state())
            if pending is not None:
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from sim_events where run_id=%s and correlation_id=%s and event_type='signal.received'",
                            (rid, pending.correlation_id),
                        )
                    ).fetchone()
                )[0] == 1
    finally:
        release.set()
        await stop(sim)


async def test_lost_commit_ack_is_failclosed_without_replaying_or_overwriting_post(seeded, monkeypatch):
    sim, _ = await running(seeded, monkeypatch)
    rid, before_time = sim.run_id, sim.clock.sim_time
    original = psycopg.AsyncConnection.commit
    target = sim.conn
    durable = None

    async def commit(conn):
        nonlocal durable
        await original(conn)
        if conn is target and durable is None and sim.clock.sim_time > before_time:
            durable = await bank(seeded)  # Настоящий COMMIT уже завершён на PostgreSQL.
            await conn.close()
            raise psycopg.OperationalError("synthetic lost COMMIT acknowledgement")

    monkeypatch.setattr(psycopg.AsyncConnection, "commit", commit)
    sim._start_loop()
    try:
        await asyncio.wait_for(asyncio.shield(sim._task), 8)
        assert durable is not None and not sim.clock.running and sim.run_id == rid
        assert await bank(seeded) == durable
        with pytest.raises(StaleSimulatorError, match="фиксации tick неизвестен.*без reset"):
            await sim.control("start")
        with pytest.raises(StaleSimulatorError, match="фиксации tick неизвестен.*без reset"):
            await sim.control("resume")
        with pytest.raises(StaleSimulatorError, match="фиксации tick неизвестен"):
            await sim.step(1)
        assert await bank(seeded) == durable  # Ни нового run, ни записи PRE поверх POST.
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()
            assert row[0] > before_time and row != (before_time, sim.rng.dump_state())
    finally:
        await stop(sim)


@pytest.mark.parametrize("action", ["pause", "stop"])
@pytest.mark.parametrize("stage", ["connect", "backoff"])
async def test_manual_control_cancels_waiting_reconnect_and_always_wins(seeded, monkeypatch, action, stage):
    sim, _ = await running(seeded, monkeypatch)
    before_time, before_rng = sim.clock.sim_time, sim.rng.dump_state()
    disconnected, entered, online = asyncio.Event(), asyncio.Event(), asyncio.Event()
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    attempts = connection_gate(monkeypatch, entered, online, blocked=stage == "connect")
    sim._start_loop()
    try:
        await asyncio.wait_for(entered.wait(), 8)
        if stage == "backoff":
            assert not sim._lock.locked()
        await asyncio.wait_for(sim.control(action), 3)
        online.set()
        await asyncio.sleep(0.05)
        assert not sim.clock.running and sim._task is None
        assert sim.run_status == ("paused" if action == "pause" else "stopped")
        assert sim.clock.sim_time == before_time and sim.rng.dump_state() == before_rng
        assert len(attempts) == 1
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (await (await conn.execute("select running from sim_state where id=1")).fetchone()) == (False,)
    finally:
        await stop(sim)


@pytest.mark.parametrize("foreign", ["pointer", "status", "rng"])
async def test_reconnect_rejects_foreign_durable_state_without_any_writes(seeded, monkeypatch, foreign):
    sim, _ = await running(seeded, monkeypatch)
    disconnected, entered, online = asyncio.Event(), asyncio.Event(), asyncio.Event()
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    connection_gate(monkeypatch, entered, online)
    sim._start_loop()
    try:
        await asyncio.wait_for(entered.wait(), 8)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            if foreign == "pointer":
                await runs.create_run(conn, kind="free", label="other owner", seed=99, sim_time=sim.clock.sim_time)
            elif foreign == "status":
                await runs.set_run_status(conn, sim.run_id, "paused")
            else:
                await conn.execute("update sim_state set rng_state=%s where id=1", (Jsonb(SimRng(99).dump_state()),))
            await conn.commit()
        expected = await bank(seeded)
        online.set()
        await asyncio.wait_for(asyncio.shield(sim._task), 8)
        assert not sim.clock.running and await bank(seeded) == expected
    finally:
        await stop(sim)


async def test_reconnect_authentication_error_is_terminal_even_before_connection_exists(seeded, monkeypatch):
    sim, _ = await running(seeded, monkeypatch)
    disconnected, entered, online = asyncio.Event(), asyncio.Event(), asyncio.Event()
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    attempts = connection_gate(monkeypatch, entered, online, auth=True)
    before = await bank(seeded)
    sim._start_loop()
    try:
        await asyncio.wait_for(asyncio.shield(sim._task), 8)
        assert entered.is_set() and len(attempts) == 1
        assert not sim.clock.running and await bank(seeded) == before
    finally:
        await stop(sim)


def test_only_connection_errors_without_a_terminal_sqlstate_are_retryable():
    assert engine._connection_lost(psycopg.OperationalError("synthetic transport"), None)
    assert engine._connection_lost(psycopg.errors.ConnectionFailure("synthetic connection"), None)
    for cls in (psycopg.errors.AdminShutdown, psycopg.errors.CrashShutdown, psycopg.errors.CannotConnectNow):
        assert engine._connection_lost(cls("synthetic shutdown"), None)
    assert not engine._connection_lost(psycopg.errors.InvalidPassword("synthetic auth"), None)
    assert not engine._connection_lost(ValueError("synthetic logic"), None)


async def test_foreign_same_run_tick_after_pre_read_cannot_be_overwritten(seeded, monkeypatch):
    sim, _ = await running(seeded, monkeypatch)
    disconnected, entered, online = asyncio.Event(), asyncio.Event(), asyncio.Event()
    online.set()
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    connection_gate(monkeypatch, entered, online)
    original = sim._reconnect_running_tick
    expected = None

    async def reconnect(tick, error):
        nonlocal expected
        await original(tick, error)
        # Реальный конкурирующий tick после readonly PRE, до повторного writer TX.
        other = Simulator(dsn=seeded)
        try:
            await other.load_state()
            # Startup loader маркирует running как interrupted; собственный fixture
            # возвращает исходный running owner без генерации нового run.
            other.run_status = "running"
            other.clock.running = True
            await runs.set_run_status(other.conn, other.run_id, "running")
            await other.persist()
            await other.conn.commit()
            await other.step(1)
            assert (
                await (await other.conn.execute("select status from sim_runs where id=%s", (other.run_id,))).fetchone()
            )[0] == "running"
            await other.conn.rollback()
            expected = await bank(seeded)
        finally:
            await stop(other)

    monkeypatch.setattr(sim, "_reconnect_running_tick", reconnect)
    sim._start_loop()
    try:
        await asyncio.wait_for(asyncio.shield(sim._task), 10)
        assert disconnected.is_set() and entered.is_set() and expected is not None
        assert not sim.clock.running and await bank(seeded) == expected
        with pytest.raises(StaleSimulatorError, match="перезапустите backend без reset"):
            await sim.step(1)
        assert await bank(seeded) == expected
    finally:
        await stop(sim)


async def test_cancel_unknown_commit_verification_keeps_guard_for_direct_step(seeded, monkeypatch):
    sim, _ = await running(seeded, monkeypatch)
    target = sim.conn
    original = psycopg.AsyncConnection.commit
    entered, online = asyncio.Event(), asyncio.Event()
    connection_gate(monkeypatch, entered, online, blocked=True)
    expected = None

    async def commit(conn):
        nonlocal expected
        await original(conn)
        if conn is target and expected is None:
            expected = await bank(seeded)
            await conn.close()
            raise psycopg.OperationalError("synthetic committed ack lost")

    monkeypatch.setattr(psycopg.AsyncConnection, "commit", commit)
    sim._start_loop()
    try:
        await asyncio.wait_for(entered.wait(), 8)
        assert expected is not None
        # Pause отменяет проверку, но не получает права переписать POST прежними часами.
        with pytest.raises(StaleSimulatorError):
            await sim.control("pause")
        assert not sim.clock.running
        with pytest.raises(StaleSimulatorError, match="перезапустите backend без reset"):
            await sim.step(1)
        assert await bank(seeded) == expected
    finally:
        online.set()
        await stop(sim)


@pytest.mark.parametrize("action", ["start", "reset_day"])
async def test_verified_pause_consumes_pre_guard_before_explicit_lifecycle_change(seeded, monkeypatch, action):
    sim, _ = await running(seeded, monkeypatch)
    disconnected, entered, online, recovered, release = (asyncio.Event() for _ in range(5))
    online.set()
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    connection_gate(monkeypatch, entered, online)
    original = sim._reconnect_running_tick

    async def reconnect(tick, error):
        await original(tick, error)
        recovered.set()
        await release.wait()

    monkeypatch.setattr(sim, "_reconnect_running_tick", reconnect)
    sim._start_loop()
    try:
        await asyncio.wait_for(recovered.wait(), 8)
        previous = sim.run_id
        await sim.control("pause")
        assert sim._reconnect_expected is None
        if action == "start":
            await sim.control("start", label="explicit new owner", seed=99, start_paused=True)
            assert sim.run_id != previous and sim.seed == 99
        else:
            before = sim.clock.sim_time
            await sim.control("reset_day")
            assert sim.clock.sim_time > before and sim.run_id == previous
        before = sim.clock.sim_time
        await sim.step(1)
        assert sim.clock.sim_time == before + dt.timedelta(minutes=1)
        assert sim.stats["ops"] > 0 and sim._reconnect_blocked is None
    finally:
        release.set()
        await stop(sim)


async def test_direct_behavior_reset_after_confirmed_pre_preserves_manual_stopped_clock(seeded, monkeypatch):
    sim, _ = await running(seeded, monkeypatch, legacy=False)
    disconnected, entered, online, recovered, release = (asyncio.Event() for _ in range(5))
    online.set()
    disconnect_first_native_batch(monkeypatch, disconnected, seeded)
    connection_gate(monkeypatch, entered, online)
    original = sim._reconnect_running_tick

    async def reconnect(tick, error):
        await original(tick, error)
        world = await sim._ensure_world()
        world.intensities.update(op=0, fault=0, client_error=0, signal_noise=0)
        await sim.conn.rollback()
        recovered.set()
        await release.wait()

    monkeypatch.setattr(sim, "_reconnect_running_tick", reconnect)
    sim._start_loop()
    try:
        await asyncio.wait_for(recovered.wait(), 8)
        rid, before = sim.run_id, sim.clock.sim_time
        snapshot = await bank(seeded)
        # Сам reset_day останавливает loop: предварительной Pause здесь нет.
        await sim.control("reset_day")
        assert sim.run_id == rid and sim.clock.sim_time > before
        assert not sim.clock.running and sim._task is None and sim._reconnect_expected is None
        assert sim.stats["ticks"] > 0 and sim.stats["ops"] == 0
        after = await bank(seeded)
        for name in ("accounts", "operations", "ledger_entries"):
            assert after[("public", name)] == snapshot[("public", name)]
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select current_run_id,sim_time,rng_state,running from sim_state where id=1")
                ).fetchone()
            ) == (rid, sim.clock.sim_time, sim.rng.dump_state(), False)
    finally:
        release.set()
        await stop(sim)
