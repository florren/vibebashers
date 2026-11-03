"""Короткий SLA не разрешает verify до release, в том числе после restart."""

import datetime as dt

import psycopg
import pytest

from app.sim.engine import Simulator
from tests.helpers import dsn

from .test_team_plan_recovery import ready

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("restart", [False, True])
async def test_short_deadline_follows_real_fsm_and_records_actual_breach(seeded, monkeypatch, restart):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, now, sim = await ready(conn, monkeypatch, seeded)
        await conn.execute(
            "update incidents set sla_due_sim=%s,take_due_sim=%s where id=%s",
            (now + dt.timedelta(hours=2), now + dt.timedelta(hours=1), incident),
        )
        await conn.execute(
            "update teams set speed_profile=%s::jsonb where code='team_deposits'",
            ('{"take_hours":[1,1],"fix_days_factor":1,"p_clarify":0,"p_sla_breach":0,"p_regression":0}',),
        )
        await conn.commit()
        try:
            await sim.step(1)
            if restart:
                await sim.conn.close()
                sim = Simulator(dsn=seeded)
                await sim.load_state()
            for _ in range(8):
                await sim.step(30)
            status, breached = await (
                await conn.execute("select status,sla_breached from incidents where id=%s", (incident,))
            ).fetchone()
            assert status == "closed" and breached
            actions = [
                r[0]
                for r in await (
                    await conn.execute(
                        "select action from team_actions where run_id=%s and incident_id=%s order by action_sim,id",
                        (run, incident),
                    )
                ).fetchall()
            ]
            assert (
                actions.index("take")
                < actions.index("fix_decision")
                < actions.index("release")
                < actions.index("verify")
                < actions.index("close")
            )
        finally:
            if sim.conn and not sim.conn.closed:
                await sim.conn.close()
