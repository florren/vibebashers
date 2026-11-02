"""T037: отдельный public run получает journal marker без смены bank clock/очереди."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import psycopg
import pytest

from app.demo.public import public_context
from app.sim.events import EventBus
from app.sim.rng import SimRng
from app.sim.team_plans import TeamPlanError
from app.sim.teams import TeamEmulator
from tests.helpers import dsn


@pytest.mark.asyncio
async def test_public_creation_marker_rolls_back_then_is_idempotent_without_bank_state_change(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        before = (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0]
        await conn.rollback()
        with pytest.raises(RuntimeError, match="rollback public creation"):
            async with conn.transaction():
                run, _ = await public_context(conn)
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'",
                            (run,),
                        )
                    ).fetchone()
                ) == (1,)
                assert (
                    await (await conn.execute("select count(*) from behavior_runs where run_id=%s", (run,))).fetchone()
                ) == (0,)
                raise RuntimeError("rollback public creation")
        assert (
            await (
                await conn.execute("select count(*) from sim_runs where settings_snapshot->>'created_by'='public_demo'")
            ).fetchone()
        ) == (0,)
        run, base = await public_context(conn)
        assert await public_context(conn) == (run, base)
        assert (
            await (
                await conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'", (run,)
                )
            ).fetchone()
        ) == (1,)
        assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()) == (0,)
        assert (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0] == before
        await conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as next_conn:
        assert await public_context(next_conn) == (run, base)
        assert (
            await (
                await next_conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'", (run,)
                )
            ).fetchone()
        ) == (1,)
        assert (await (await next_conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[
            0
        ] == before


@pytest.mark.asyncio
async def test_existing_public_planless_history_is_not_silently_enrolled(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, base = await public_context(conn)
        await conn.execute("delete from sim_events where run_id=%s and event_type='team.runtime_started'", (run,))
        incident = (
            await (
                await conn.execute(
                    "insert into incidents(run_id,title,incident_type,product_code,team_code,system_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) values(%s,'synthetic legacy public','tech_fault','deposit','team_deposits','sub_deposits','medium','high',2,'routed','scenario',%s,%s,%s) returning id",
                    (run, base, base + dt.timedelta(days=3), base + dt.timedelta(hours=4)),
                )
            ).fetchone()
        )[0]
        await conn.commit()
        assert await public_context(conn) == (run, base)
        before = (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0]
        rng = SimRng(1)
        state = rng.dump_state()
        team = TeamEmulator(rng, conn, EventBus(conn), run)
        await team.load()
        with pytest.raises(TeamPlanError, match="legacy_team_plan_unknown"):
            await team.tick(base, SimpleNamespace(active_faults=[]))
        assert rng.dump_state() == state
        assert (await (await conn.execute("select status from incidents where id=%s", (incident,))).fetchone()) == (
            "routed",
        )
        assert (
            await (
                await conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'", (run,)
                )
            ).fetchone()
        ) == (0,)
        assert (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0] == before
