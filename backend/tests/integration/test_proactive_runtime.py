"""Main lifespan + реальные actors, synthetic own DB/Mock и HTTP egress bomb."""

import psycopg
import pytest

from app.sim import scenarios
from app.sim.proactive_scenario import case
from tests.helpers import dsn
from tests.integration.test_proactive_prepare import mass_seeded as mass_seeded
from tests.proactive_runtime import offline_main_runtime, run_prepared_mass_case


@pytest.mark.asyncio
async def test_main_runtime_executes_scripted_native_phases_with_all_actors_and_no_external_http(
    mass_seeded, monkeypatch, tmp_path
):
    async with offline_main_runtime(mass_seeded, monkeypatch, tmp_path) as (app, external):
        await run_prepared_mass_case(app, mass_seeded, monkeypatch)
        run = app.state.sim.run_id
        async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
            context = await case(conn, run)
            assert context is not None and "completed" in context.events
            result = await scenarios.evaluate(conn, scenarios.get("mass_notifications"), run)
            assert result["passed"], result["checks"]
            assert result["counts"]["affected"] == 120
            assert result["counts"]["notified_before_first_complaint"] >= 90
            assert result["counts"]["complaints"] == result["counts"]["deduplicated"] == 30
            assert result["counts"]["care_positive"] >= 90
            assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()) == (
                31,
            )
            assert (
                await (
                    await conn.execute("select count(*) from v_cabinet_signal_facts where run_id=%s", (run,))
                ).fetchone()
            ) == (30,)
            assert (
                await (await conn.execute("select count(*) from ledger_entries where run_id=%s", (run,))).fetchone()
            ) == (0,)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from human_decisions where sim_run_id=%s and decision is null", (run,)
                    )
                ).fetchone()
            )[0] >= 1
            assert (await (await conn.execute("select status from sim_runs where id=%s", (run,))).fetchone()) == (
                "paused",
            )
            assert app.state.sim.clock.sim_time == context.observed_at
        assert external == []
