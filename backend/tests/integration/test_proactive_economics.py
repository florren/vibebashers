"""T-039: native cohort не равен числу служебных/повторных сигналов."""

import datetime as dt

import psycopg
import pytest

from app.economics import dcltv
from tests.helpers import dsn

from .test_proactive_fault import operation
from .test_proactive_recovery import prepare


@pytest.mark.asyncio
async def test_native_economics_ignores_counter_and_future_operation(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, state, _ = await prepare(conn)
        incident = (await (await conn.execute("select id from incidents where run_id=%s", (run,))).fetchone())[0]
        await conn.execute("update faults set affected_clients=999,impact_count=999 where id=%s", (fid,))
        await operation(conn, run, fid, people[1], at + dt.timedelta(minutes=1))
        result = await dcltv.compute_incident(conn, incident, sim_time=at)
        assert result["affected_count"] == 1
        assert (
            await (await conn.execute("select mass_impact from incidents where id=%s", (incident,))).fetchone()
        ) == (1,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "missing_op",
        "future_op",
        "bad_system",
        "bad_code",
        "mass",
        "missing_provenance",
        "foreign_cause",
        "future_clock",
    ],
)
async def test_native_economics_invalid_facts_fail_before_financial_write(seeded, invalid):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, state, _ = await prepare(conn)
        incident = (await (await conn.execute("select id from incidents where run_id=%s", (run,))).fetchone())[0]
        before = await (
            await conn.execute("select to_jsonb(e) from incident_economics e where incident_id=%s", (incident,))
        ).fetchone()
        when = at
        if invalid == "missing_op":
            await conn.execute("update operations set fault_id=null where run_id=%s", (run,))
        elif invalid == "future_op":
            await conn.execute(
                "update operations set started_sim=%s where run_id=%s", (at + dt.timedelta(hours=1), run)
            )
        elif invalid == "bad_system":
            await conn.execute("update operations set system_path=ARRAY['crm'] where run_id=%s", (run,))
        elif invalid == "bad_code":
            await conn.execute("update operations set error_code='DEP-TIMEOUT-503' where run_id=%s", (run,))
        elif invalid == "mass":
            await conn.execute("update incidents set mass_impact=999 where id=%s", (incident,))
        elif invalid == "missing_provenance":
            await conn.execute("delete from ingest_messages where signal_id=%s", (sid,))
        elif invalid == "foreign_cause":
            await conn.execute("update incidents set fault_id=null where id=%s", (incident,))
        else:
            when += dt.timedelta(hours=1)
        with pytest.raises(ValueError, match="fault_monitor economics"):
            await dcltv.compute_incident(conn, incident, sim_time=when)
        assert (
            await (
                await conn.execute("select to_jsonb(e) from incident_economics e where incident_id=%s", (incident,))
            ).fetchone()
            == before
        )
