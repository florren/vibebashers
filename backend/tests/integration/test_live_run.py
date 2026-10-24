"""T-180: ensure_live_run и независимость живого запуска от сим-часов (ТЗ 4.7)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest

from app.sim.engine import Simulator
from app.sim.runs import ensure_live_run
from tests.helpers import dsn

pytestmark = pytest.mark.integration

_STATE_SQL = (
    "select sim_time, day_no, speed, running, seed, phase, current_run_id, "
    "rng_state::text, last_tick_at, intensities::text from sim_state where id = 1"
)
_RESTORE_SQL = (
    "update sim_state set sim_time = %s, day_no = %s, speed = %s, running = %s, seed = %s, phase = %s, "
    "current_run_id = %s, rng_state = %s::jsonb, last_tick_at = %s, intensities = %s::jsonb, updated_at = now() "
    "where id = 1"
)
_ROW_TABLES = ("signals", "incidents", "operations", "sim_events", "faults")


@asynccontextmanager
async def _guard(seeded: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Откатывает sim_state и удаляет запуски, созданные тестом: фикстура seeded общая на сессию."""
    conn = await psycopg.AsyncConnection.connect(dsn(seeded))
    snap = await (await conn.execute(_STATE_SQL)).fetchone()
    max_row = await (await conn.execute("select coalesce(max(id), 0) from sim_runs")).fetchone()
    if snap is None or max_row is None:
        await conn.close()
        raise RuntimeError("нет sim_state")
    max_id = int(max_row[0])
    try:
        yield conn
    finally:
        try:
            await conn.rollback()
        except Exception:
            pass
        try:
            await conn.close()
        except Exception:
            pass
        cleanup = await psycopg.AsyncConnection.connect(dsn(seeded))
        try:
            await cleanup.execute(_RESTORE_SQL, snap)
            await cleanup.execute("delete from sim_runs where id > %s", (max_id,))
            await cleanup.commit()
        finally:
            await cleanup.close()


async def _pointer(conn: psycopg.AsyncConnection[Any]) -> tuple[Any, ...]:
    row = await (
        await conn.execute("select current_run_id, sim_time, running, seed from sim_state where id = 1")
    ).fetchone()
    assert row is not None
    return row


async def _status(conn: psycopg.AsyncConnection[Any], run_id: int) -> str:
    row = await (await conn.execute("select status from sim_runs where id = %s", (run_id,))).fetchone()
    assert row is not None
    return str(row[0])


async def _counters(conn: psycopg.AsyncConnection[Any], run_id: int) -> tuple[Any, ...]:
    row = await (
        await conn.execute(
            "select signals, incidents, incidents_open, sla_breached, hitl_requests, churned, tokens, "
            "prevented_loss_rub, realized_loss_rub from v_run_counters where run_id = %s",
            (run_id,),
        )
    ).fetchone()
    assert row is not None
    return row


async def _run_rows(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _ROW_TABLES:
        row = await (await conn.execute(f"select count(*) from {table} where run_id = %s", (run_id,))).fetchone()
        assert row is not None
        counts[table] = int(row[0])
    return counts


async def _count_live(conn: psycopg.AsyncConnection[Any]) -> int:
    row = await (await conn.execute("select count(*) from sim_runs where kind = 'live'")).fetchone()
    assert row is not None
    return int(row[0])


async def test_ensure_live_run_creates_one_when_pointer_empty(seeded: str) -> None:
    async with _guard(seeded) as conn:
        baseline_id, sim_time, running, seed = await _pointer(conn)
        assert baseline_id is not None and running is False
        baseline_id = int(baseline_id)
        status_before = await _status(conn, baseline_id)
        rows_before = await _run_rows(conn, baseline_id)
        counters_before = await _counters(conn, baseline_id)
        live_before = await _count_live(conn)
        assert rows_before["signals"] > 0

        await conn.execute("update sim_state set current_run_id = null where id = 1")
        first = await ensure_live_run(conn)
        second = await ensure_live_run(conn)
        assert first == second

        created = await (
            await conn.execute(
                "select kind, label, reset_mode, seed, started_sim, parent_run_id from sim_runs where id = %s",
                (first,),
            )
        ).fetchone()
        assert created is not None
        kind, label, reset_mode, run_seed, started_sim, parent = created
        assert kind == "live" and label == "живой показ" and reset_mode == "none"
        assert int(run_seed) == int(seed) and started_sim == sim_time and parent is None
        assert await _count_live(conn) == live_before + 1

        current_id, sim_time_after, running_after, _seed_after = await _pointer(conn)
        assert current_id == first and sim_time_after == sim_time and running_after is False
        assert await _status(conn, baseline_id) == status_before
        assert await _run_rows(conn, baseline_id) == rows_before
        assert await _counters(conn, baseline_id) == counters_before
        assert (await _run_rows(conn, first))["signals"] == 0
        assert int((await _counters(conn, first))[0]) == 0


async def test_engine_persist_keeps_live_run_and_sim_time(seeded: str) -> None:
    async with _guard(seeded) as conn:
        _baseline_id, sim_time, running, _seed = await _pointer(conn)
        assert running is False
        await conn.execute("update sim_state set current_run_id = null, running = false where id = 1")
        await conn.commit()

        sim = Simulator(dsn=seeded)
        live_id = 0
        try:
            await sim.load_state()
            assert sim.run_id is None
            assert sim.clock.running is False and sim.clock.sim_time == sim_time
            live_id = await sim.ensure_live_run()
            assert await sim.ensure_live_run() == live_id == sim.run_id
            assert sim.clock.running is False and sim._task is None and sim.world is None
            assert sim.stats["ticks"] == 0 and sim.run_status is not None
            await sim.persist()
            assert sim.conn is not None
            await sim.conn.commit()

            saved = await (
                await conn.execute("select current_run_id, sim_time, running from sim_state where id = 1")
            ).fetchone()
            assert saved is not None
            assert saved[0] == live_id and saved[1] == sim_time and saved[2] is False
            created = await (
                await conn.execute("select kind, label from sim_runs where id = %s", (live_id,))
            ).fetchone()
            assert created == ("live", "живой показ")
            assert (await _run_rows(conn, live_id))["signals"] == 0
        finally:
            await sim.shutdown()


async def test_filled_pointer_keeps_baseline_and_paused_clock(seeded: str) -> None:
    async with _guard(seeded) as conn:
        baseline_id, sim_time, running, _seed = await _pointer(conn)
        assert baseline_id is not None and running is False
        baseline_id = int(baseline_id)
        status_before = await _status(conn, baseline_id)
        rows_before = await _run_rows(conn, baseline_id)
        counters_before = await _counters(conn, baseline_id)
        live_before = await _count_live(conn)
        assert rows_before["signals"] > 0

        assert await ensure_live_run(conn) == baseline_id
        assert await _count_live(conn) == live_before
        assert await _status(conn, baseline_id) == status_before
        assert await _run_rows(conn, baseline_id) == rows_before
        assert await _counters(conn, baseline_id) == counters_before
        await conn.commit()

        sim = Simulator(dsn=seeded)
        try:
            await sim.load_state()
            assert sim.run_id == baseline_id
            held_status = sim.run_status
            assert await sim.ensure_live_run() == baseline_id
            assert sim.run_id == baseline_id and sim.run_status == held_status
            assert sim.clock.running is False and sim.clock.sim_time == sim_time
            await sim.control("pause")
            assert sim.clock.running is False and sim._task is None and sim.stats["ticks"] == 0
            assert sim.clock.sim_time == sim_time
        finally:
            await sim.shutdown()

        current_id, sim_time_after, running_after, _seed_after = await _pointer(conn)
        assert current_id == baseline_id and sim_time_after == sim_time and running_after is False
        assert await _count_live(conn) == live_before
        assert await _status(conn, baseline_id) == status_before
        assert await _run_rows(conn, baseline_id) == rows_before
        assert await _counters(conn, baseline_id) == counters_before
