"""B03 (T-031/T-033/T-035/T-040-минимум): симулятор на живой PostgreSQL — шаг, события по контрактам, NOTIFY → маршрутизация WS, запуски."""

from __future__ import annotations

import asyncio
import datetime as dt
import json

import psycopg
import pytest

from app.contracts.registry import validate
from app.realtime.notify import route
from app.sim.clock import MSK, add_working_days, add_working_hours, is_working_time, phase_of
from app.sim.engine import Simulator


def test_clock_helpers() -> None:
    fri = dt.datetime(2026, 11, 6, 17, 0, tzinfo=MSK)  # пятница
    assert add_working_days(fri, 1).weekday() == 0  # понедельник
    assert add_working_days(fri, 5) == dt.datetime(2026, 11, 13, 17, 0, tzinfo=MSK)
    assert add_working_hours(fri, 2) == dt.datetime(2026, 11, 9, 10, 0, tzinfo=MSK)  # 1 ч в пятницу + 1 ч в понедельник
    assert not is_working_time(dt.datetime(2026, 11, 7, 12, 0, tzinfo=MSK))
    assert phase_of(dt.datetime(2026, 11, 9, 7, 0, tzinfo=MSK)) == "morning"
    assert phase_of(dt.datetime(2026, 11, 9, 23, 30, tzinfo=MSK)) == "night"


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def sim(seeded: str) -> Simulator:
    return Simulator(seed=7, dsn=seeded)


def test_step_generates_contract_valid_events_and_new_run(sim: Simulator, conn: psycopg.Connection) -> None:
    async def run() -> None:
        await sim.load_state()
        assert sim.run_status == "completed"  # baseline из сида
        await sim.control("set_preset", preset="demo_5min")
        await sim.step(60)
        await sim.step(60)
        await sim.step(120)
        await sim.shutdown()

    asyncio.run(run())
    assert (
        sim.run_id is not None and sim.run_status == "running" and sim.clock.sim_time.astimezone(MSK).hour == 13
    )  # 09:00 + 4 ч
    assert sim.stats["ops"] > 10 and sim.stats["ticks"] == 4  # 60 + 60 + 2×60
    rows = conn.execute("select event_type, payload from sim_events where run_id = %s", (sim.run_id,)).fetchall()
    assert rows and any(t.startswith("op.") for t, _ in rows)
    for event_type, payload in rows:
        fam = event_type.split(".")[0]
        schema = {
            "op": "sim/op",
            "fault": "sim/fault",
            "client_error": "sim/client_error",
            "signal": "sim/signal",
            "abs": "sim/abs",
            "sla": "sim/sla",
            "team": "sim/team_action",
            "escalation": "sim/escalation",
            "review": "sim/review",
        }[fam]
        assert validate(payload, schema) == [], (event_type, payload)
    assert (
        conn.execute("select count(*) from operations where run_id = %s", (sim.run_id,)).fetchone()[0]
        == sim.stats["ops"]
    )
    assert conn.execute("select count(*) from sim_events where run_id is null").fetchone()[0] == 0
    # запуск: baseline → stopped? нет: baseline был completed, новый run kind=free, parent = baseline
    kind, parent, status = conn.execute(
        "select kind, parent_run_id, status from sim_runs where id = %s", (sim.run_id,)
    ).fetchone()
    assert kind == "free" and parent is not None and status == "running"
    st = conn.execute(
        "select current_run_id, running, rng_state is not null, last_tick_at is not null from sim_state"
    ).fetchone()
    assert st[0] == sim.run_id and st[1] is False and st[2] and st[3]


def test_notify_routes_to_ws_topics(sim: Simulator, seeded: str) -> None:
    received: list[tuple[str, str, dict, int | None]] = []

    async def run() -> None:
        listener = await psycopg.AsyncConnection.connect(_dsn(seeded), autocommit=True)
        await listener.execute("LISTEN sim_events")
        await listener.execute("LISTEN signals")
        await listener.execute("LISTEN runs")
        await sim.load_state()
        await sim.control("start", label="тест NOTIFY")
        await sim.control("pause")
        await sim.step(60)
        await sim.shutdown()
        gen = listener.notifies(timeout=2.0)
        async for n in gen:
            r = route(n.channel, n.payload)
            if r:
                received.append(r)
        await listener.close()

    asyncio.run(run())
    topics = {(t, ty.split(".")[0]) for t, ty, _, _ in received}
    assert ("runs", "started") in topics
    assert ("sim", "op") in topics
    assert all(rid == sim.run_id for _, _, _, rid in received if rid is not None)
    env_sample = next(d for t, ty, d, _ in received if t == "sim" and ty.startswith("op."))
    assert validate(env_sample, "envelope") == []


def test_stop_and_resume_statuses(sim: Simulator, conn: psycopg.Connection) -> None:
    async def run() -> dict:
        await sim.load_state()
        await sim.control("start", label="стоп/резюм")
        await sim.control("pause")
        assert sim.run_status == "paused"
        await sim.control("resume")
        assert sim.run_status == "running"
        await sim.control("pause")
        state = await sim.control("stop")
        await sim.shutdown()
        return state

    state = asyncio.run(run())
    assert state["current_run_status"] == "stopped" and state["running"] is False
    status, summary = conn.execute("select status, summary from sim_runs where id = %s", (sim.run_id,)).fetchone()
    assert status == "stopped" and "signals" in summary
    with pytest.raises(ValueError):
        asyncio.run(_jump_back(sim))


async def _jump_back(sim: Simulator) -> None:
    await sim.load_state()
    try:
        await sim.control("jump_to", sim_time=sim.clock.sim_time - dt.timedelta(hours=1))
    finally:
        await sim.shutdown()


def test_sim_events_jsonable() -> None:
    from app.sim.events import dumps

    assert json.loads(dumps({"t": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)}))["t"].startswith("2026-01-01")
