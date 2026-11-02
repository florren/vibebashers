"""T039 prepared native rows: atomic/idempotent, no signal/gold/model synthesis."""

import copy
import random

import psycopg
import pytest
from scripts.seed.clients import seed_clients

from app.sim import scenarios
from app.sim.proactive_scenario import ScriptedScenarioError, plan, preflight, prepare
from tests.helpers import dsn, new_run


@pytest.fixture
def mass_seeded(seeded):
    with psycopg.connect(dsn(seeded)) as conn:
        now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
        seed_clients(conn.cursor(), random.Random(42), 5000, now)
    return seeded


def scenario():
    data = copy.deepcopy(scenarios.get("mass_notifications"))
    if "script" in data:
        return data
    data["fault"]["expected_duration_min"] = 90
    data["operation"] = {k: v for k, v in data["inject"][0]["client"]["operation"].items() if k != "error_code"}
    data["script"] = {
        "source_mode": "prepared_native",
        "initial_step_min": 1,
        "complaint_step_min": 0.1,
        "owner_observation_step_min": 0.1,
        "complaints": 30,
        "minimum_notices": 90,
    }
    data["complaint_templates"] = [{"channel": item["channel"], "text": item["text"]} for item in data.pop("inject")]
    return data


async def current(conn):
    run = await new_run(conn, "T039 prepared case", kind="scenario")
    await conn.execute("update sim_runs set scenario_id='mass_notifications',status='paused' where id=%s", (run,))
    await conn.execute("update sim_state set running=false where id=1")
    await conn.commit()
    return run


@pytest.mark.asyncio
async def test_prepared_native_source_is_atomic_idempotent_without_early_service_anchor(mass_seeded):
    async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
        spec = plan(scenario())
        assert spec is not None
        run = await current(conn)
        cohort = await preflight(conn, spec)
        assert len(cohort) == 120
        before = await (
            await conn.execute(
                "select id,consents,contacts,region_code from clients where id=any(%s) order by id",
                ([person["id"] for person in cohort],),
            )
        ).fetchall()
        await conn.commit()
        async with conn.transaction():
            first = await prepare(conn, run, spec)
            assert await prepare(conn, run, spec) == first
        assert len(first.payload["operation_ids"]) == 120
        assert await (
            await conn.execute(
                "select count(*) from operations where run_id=%s and behavior_valid_failed_operation(id,%s)", (run, run)
            )
        ).fetchone() == (120,)
        assert await (
            await conn.execute("select affected_clients,impact_count from faults where run_id=%s", (run,))
        ).fetchall() == [(120, 120)]
        assert await (
            await conn.execute(
                "select count(*) from sim_events where run_id=%s and event_type='scenario.proactive_prepared'", (run,)
            )
        ).fetchone() == (1,)
        assert not await (await conn.execute("select 1 from signals where run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from agent_runs where sim_run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
        assert (
            await (
                await conn.execute(
                    "select id,consents,contacts,region_code from clients where id=any(%s) order by id",
                    ([person["id"] for person in cohort],),
                )
            ).fetchall()
            == before
        )
        changed = scenario()
        changed["complaint_templates"][0]["text"] += " Повторное описание."
        other = plan(changed)
        with pytest.raises(ScriptedScenarioError, match="script_changed"):
            await prepare(conn, run, other)
        assert await (await conn.execute("select count(*) from faults where run_id=%s", (run,))).fetchone() == (1,)


@pytest.mark.asyncio
async def test_insufficient_lite_cohort_fails_without_native_rows(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        spec = plan(scenario())
        run = await current(conn)
        journal_before = await (
            await conn.execute("select * from sim_events where run_id=%s order by id", (run,))
        ).fetchall()
        with pytest.raises(ScriptedScenarioError, match="insufficient_cohort"):
            await prepare(conn, run, spec)
        assert not await (await conn.execute("select 1 from faults where run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from operations where run_id=%s", (run,))).fetchone()
        assert (
            await (await conn.execute("select * from sim_events where run_id=%s order by id", (run,))).fetchall()
            == journal_before
        )


@pytest.mark.asyncio
async def test_insufficient_native_consent_fails_without_changing_contacts(mass_seeded):
    async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
        spec = plan(scenario())
        run = await current(conn)
        # Только synthetic privacy fixture, production producer это не меняет.
        await conn.execute("update clients set consents=jsonb_build_object('proactive',false)")
        await conn.commit()
        with pytest.raises(ScriptedScenarioError, match="insufficient_consents"):
            await prepare(conn, run, spec)
        assert not await (await conn.execute("select 1 from faults where run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from operations where run_id=%s", (run,))).fetchone()


@pytest.mark.asyncio
async def test_prepare_accepts_only_actual_outer_transaction_on_autocommit_connection(mass_seeded):
    async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
        run = await current(conn)
    spec = plan(scenario())
    async with await psycopg.AsyncConnection.connect(dsn(mass_seeded), autocommit=True) as conn:
        with pytest.raises(ValueError, match="внешнюю tick transaction"):
            await prepare(conn, run, spec)
        assert not await (await conn.execute("select 1 from faults where run_id=%s", (run,))).fetchone()
        async with conn.transaction():
            record = await prepare(conn, run, spec)
        assert len(record.payload["operation_ids"]) == 120
        assert (await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()) == (
            120,
        )


@pytest.mark.asyncio
async def test_prepared_partial_failure_rolls_back_all_native_rows_and_rng(mass_seeded, monkeypatch):
    from app.sim.events import EventBus

    async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
        run = await current(conn)
        journal_before = await (
            await conn.execute("select * from sim_events where run_id=%s order by id", (run,))
        ).fetchall()
        before = await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()
        await conn.commit()
        original = EventBus.emit
        seen = 0

        async def interrupted(bus, run_id, event_type, *args, **kwargs):
            nonlocal seen
            if event_type == "op.failed":
                seen += 1
                if seen == 60:
                    raise RuntimeError("synthetic interrupted preparation")
            return await original(bus, run_id, event_type, *args, **kwargs)

        monkeypatch.setattr(EventBus, "emit", interrupted)
        with pytest.raises(RuntimeError, match="synthetic interrupted"):
            async with conn.transaction():
                await prepare(conn, run, plan(scenario()))
        assert not await (await conn.execute("select 1 from faults where run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from operations where run_id=%s", (run,))).fetchone()
        assert (
            await (await conn.execute("select * from sim_events where run_id=%s order by id", (run,))).fetchall()
            == journal_before
        )
        assert await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone() == before
        monkeypatch.setattr(EventBus, "emit", original)
        record = await prepare(conn, run, plan(scenario()))
        assert len(record.payload["operation_ids"]) == 120


@pytest.mark.asyncio
async def test_script_window_never_shortens_actual_primary_due_to_fit_case(mass_seeded):
    data = scenario()
    data["script"]["owner_observation_step_min"] = 0.95
    async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
        run = await current(conn)
        with pytest.raises(ScriptedScenarioError, match="script_overlaps_native_due"):
            await prepare(conn, run, plan(data))
        assert not await (await conn.execute("select 1 from faults where run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from operations where run_id=%s", (run,))).fetchone()
