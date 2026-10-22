"""Изоляция запусков эмуляции (T-146): данные одного запуска не видны в другом, нет «сирот» без run_id."""

from __future__ import annotations

import psycopg
import pytest

from app.agent.graph import process_signal
from app.sim import scenarios as sc
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, run_agent_on, sim_now

RUN_SCOPED_TABLES = (
    "signals",
    "incidents",
    "agent_runs",
    "notifications",
    "tasks",
    "followups",
    "sim_events",
    "operations",
)


async def test_two_runs_do_not_leak(seeded: str) -> None:
    scenario = sc.get("double_fee")
    assert scenario
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_a = await new_run(conn, "iso-A", scenario_id="double_fee")
        for item in await sc.inject(conn, scenario, run_a, sim_time=await sim_now(conn)):
            await conn.commit()
            await process_signal(conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
        run_b = await new_run(conn, "iso-B")
        sig_b, _ = await run_agent_on(conn, "Спасибо, всё решили быстро, молодцы!", client_id=3, run_id=run_b)

        async def ids(table: str, run_id: int) -> set[int]:
            col = "sim_run_id" if table == "agent_runs" else "run_id"
            rows = await (await conn.execute(f"select id from {table} where {col} = %s", (run_id,))).fetchall()  # noqa: S608
            return {int(r[0]) for r in rows}

        for table in ("signals", "incidents", "agent_runs"):
            assert not (await ids(table, run_a)) & (await ids(table, run_b)), table
        assert sig_b in await ids("signals", run_b)
        assert sig_b not in await ids("signals", run_a)
        a_inc = await ids("incidents", run_a)
        assert a_inc and not await ids("incidents", run_b)
        # инцидент запуска A не должен «склеивать» сигналы запуска B: контекст агента ограничен run_id
        row = await (
            await conn.execute("select decision->>'link_incident_id' from signals where id = %s", (sig_b,))
        ).fetchone()
        assert row and row[0] in (None, "", "null")


async def test_no_orphans_without_run_id(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        for table in RUN_SCOPED_TABLES:
            col = "sim_run_id" if table in ("agent_runs", "followups") else "run_id"
            row = await (
                await conn.execute(f"select count(*) from {table} where {col} is null", ())  # noqa: S608
            ).fetchone()
            assert row and int(row[0]) == 0, f"{table}: {row[0]} строк без {col}"


@pytest.mark.parametrize("table", ["signals", "incidents", "agent_runs"])
async def test_counters_follow_run(seeded: str, table: str) -> None:
    """v_run_counters считает только свои строки."""
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rows = await (await conn.execute("select run_id, to_jsonb(v) from v_run_counters v order by run_id")).fetchall()
        assert rows
        for run_id, counters in rows:
            col = "sim_run_id" if table == "agent_runs" else "run_id"
            cnt = await (await conn.execute(f"select count(*) from {table} where {col} = %s", (run_id,))).fetchone()  # noqa: S608
            key = {"signals": "signals", "incidents": "incidents", "agent_runs": None}[table]
            if key is not None:
                assert int(counters[key]) == int(cnt[0]), (run_id, key)
