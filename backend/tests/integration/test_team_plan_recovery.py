"""T-037: план до первого due действия должен переживать потерю процесса."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from app.sim.engine import Simulator
from app.sim.teams import _plan_blob
from tests.helpers import dsn

from .test_behavior_runtime import setup


async def ready(conn, monkeypatch, seeded):
    run, _, now, sim = await setup(conn, monkeypatch, seeded)
    incident = (
        await (
            await conn.execute(
                "insert into incidents(run_id,title,incident_type,product_code,team_code,system_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) "
                "values(%s,'durable team plan','tech_fault','deposit','team_deposits','sub_deposits','medium','high',2,'routed','scenario',%s,%s,%s) returning id",
                (run, now, now + dt.timedelta(days=3), now + dt.timedelta(hours=4)),
            )
        ).fetchone()
    )[0]
    await conn.execute(
        "update teams set speed_profile=jsonb_set(speed_profile,'{take_hours}','[2,2]'::jsonb) where code='team_deposits'"
    )
    await conn.commit()
    return run, incident, now, sim


@pytest.mark.asyncio
async def test_plan_before_first_due_action_survives_fresh_owner_without_rng_draw(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, now, sim = await ready(conn, monkeypatch, seeded)
        before = sim.rng.dump_state()
        await sim.step(1)
        expected = _plan_blob(sim.world.team_emulator.plans[incident])
        state, clock = sim.rng.dump_state(), sim.clock.sim_time
        assert state != before
        assert min(dt.datetime.fromisoformat(step["at"]) for step in expected["steps"]) > clock
        assert (await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        await sim.conn.close()
        restored = Simulator(dsn=seeded)
        try:
            await restored.load_state()
            await restored._ensure_world()
            assert restored.clock.sim_time == clock and restored.rng.dump_state() == state
            assert incident in restored.world.team_emulator.plans
            assert _plan_blob(restored.world.team_emulator.plans[incident]) == expected
        finally:
            if restored.conn:
                await restored.conn.close()


@pytest.mark.asyncio
async def test_plan_and_rng_rollback_then_retry_without_phantom_event_or_early_action(seeded, monkeypatch):
    from app.sim.events import EventBus

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, now, sim = await ready(conn, monkeypatch, seeded)
        before = sim.rng.dump_state()
        original = EventBus.emit
        attempted = []

        async def fail_after_plan(bus, *args, **kwargs):
            result = await original(bus, *args, **kwargs)
            if args[1] == "team.plan":
                attempted.append(args[2]["plan"])
                raise RuntimeError("rollback after native plan")
            return result

        monkeypatch.setattr(EventBus, "emit", fail_after_plan)
        with pytest.raises(RuntimeError, match="rollback after native plan"):
            await sim.step(1)
        assert sim.clock.sim_time == now and sim.rng.dump_state() == before
        assert sim.world.team_emulator.plans == {}
        assert (
            await (
                await conn.execute("select count(*) from sim_events where run_id=%s and event_type='team.plan'", (run,))
            ).fetchone()
        ) == (0,)
        assert (await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        monkeypatch.setattr(EventBus, "emit", original)
        await sim.step(1)
        assert _plan_blob(sim.world.team_emulator.plans[incident]) == attempted[0]
        assert (
            await (
                await conn.execute("select count(*) from sim_events where run_id=%s and event_type='team.plan'", (run,))
            ).fetchone()
        ) == (1,)
        assert (await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        await sim.conn.close()


@pytest.mark.asyncio
async def test_two_sim_owners_commit_exactly_one_plan_and_reject_stale_clock_rng(seeded, monkeypatch):
    import asyncio

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, now, first = await ready(conn, monkeypatch, seeded)
        other = Simulator(dsn=seeded)
        await other.load_state()
        try:
            results = await asyncio.wait_for(asyncio.gather(first.step(1), other.step(1), return_exceptions=True), 15)
            assert sum(value is None for value in results) == 1
            errors = [value for value in results if isinstance(value, Exception)]
            assert len(errors) == 1 and isinstance(errors[0], ValueError) and "устарел" in str(errors[0])
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_events where run_id=%s and event_type='team.plan'", (run,)
                    )
                ).fetchone()
            ) == (1,)
            assert (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone()) == (
                now + dt.timedelta(minutes=1),
            )
            assert (
                await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()
            ) == (0,)
        finally:
            await first.conn.close()
            await other.conn.close()


@pytest.mark.asyncio
async def test_enrollment_empty_legacy_is_transactional_idempotent_and_rng_free(seeded, monkeypatch):
    from app.sim.team_plans import ensure_runtime

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        await conn.execute("delete from sim_events where run_id=%s and event_type='team.runtime_started'", (run,))
        await conn.commit()
        before = sim.rng.dump_state()
        await ensure_runtime(conn, run, now)
        await ensure_runtime(conn, run, now)
        await conn.rollback()
        assert (
            await (
                await conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'", (run,)
                )
            ).fetchone()
        ) == (0,)
        await ensure_runtime(conn, run, now)
        await ensure_runtime(conn, run, now)
        await conn.commit()
        assert sim.rng.dump_state() == before
        assert (
            await (
                await conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'", (run,)
                )
            ).fetchone()
        ) == (1,)
        await sim.conn.close()


@pytest.mark.asyncio
async def test_unknown_legacy_preaction_plan_refuses_before_clock_rng_and_generated_effects(seeded, monkeypatch):
    from app.sim.team_plans import TeamPlanError

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, now, sim = await ready(conn, monkeypatch, seeded)
        await conn.execute("delete from sim_events where run_id=%s and event_type='team.runtime_started'", (run,))
        await conn.commit()
        state = sim.rng.dump_state()
        sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 100)
        with pytest.raises(TeamPlanError, match="legacy_team_plan_unknown") as err:
            await sim.step(1)
        assert str(incident) in str(err.value) and "данные сохранены" in str(err.value)
        assert sim.rng.dump_state() == state and sim.clock.sim_time == now
        assert (await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        assert (await (await conn.execute("select count(*) from sim_events where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        assert (await (await conn.execute("select status from incidents where id=%s", (incident,))).fetchone()) == (
            "routed",
        )
        await sim.conn.close()


@pytest.mark.asyncio
async def test_action_only_legacy_blob_is_preserved_without_redraw_or_early_action(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, _, sim = await ready(conn, monkeypatch, seeded)
        await sim.step(1)
        take_at = next(step.at for step in sim.world.team_emulator.plans[incident].steps if step.action == "take")
        await sim.step((take_at - sim.clock.sim_time).total_seconds() / 60)
        expected, state = _plan_blob(sim.world.team_emulator.plans[incident]), sim.rng.dump_state()
        before = await (
            await conn.execute(
                "select id,action,action_sim,payload from team_actions where run_id=%s order by id", (run,)
            )
        ).fetchall()
        assert before and before[0][1] == "take"
        # Только synthetic fixture моделирует старый action-only формат без native journal.
        await conn.execute(
            "delete from sim_events where run_id=%s and event_type in ('team.plan','team.runtime_started')", (run,)
        )
        await conn.commit()
        await sim.conn.close()
        restored = Simulator(dsn=seeded)
        try:
            await restored.load_state()
            await restored._ensure_world()
            assert restored.rng.dump_state() == state
            assert _plan_blob(restored.world.team_emulator.plans[incident]) == expected
            assert (
                await (
                    await conn.execute(
                        "select id,action,action_sim,payload from team_actions where run_id=%s order by id", (run,)
                    )
                ).fetchall()
                == before
            )
        finally:
            await restored.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["duplicate", "foreign_incident", "version", "naive", "invalid_time", "team"])
async def test_native_plan_invalid_lineage_refuses_without_clock_rng_or_action_effects(seeded, monkeypatch, bad):
    from psycopg.types.json import Jsonb

    from app.sim.team_plans import TeamPlanError
    from tests.helpers import new_run

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        foreign = await new_run(conn, "foreign plan facts", kind="free")
        run, incident, _, sim = await ready(conn, monkeypatch, seeded)
        await sim.step(1)
        state, clock = sim.rng.dump_state(), sim.clock.sim_time
        event = await (
            await conn.execute(
                "select id,payload,sim_time from sim_events where run_id=%s and event_type='team.plan'", (run,)
            )
        ).fetchone()
        payload = event[1]
        if bad == "duplicate":
            await conn.execute(
                "insert into sim_events(run_id,event_type,payload,sim_time) values(%s,'team.plan',%s,%s)",
                (run, Jsonb(payload), clock),
            )
        else:
            if bad == "foreign_incident":
                await conn.execute("update incidents set run_id=%s where id=%s", (foreign, incident))
            elif bad == "version":
                payload["version"] = 2
            elif bad == "naive":
                payload["plan"]["steps"][0]["at"] = "2026-11-09T09:00:00"
            elif bad == "invalid_time":
                payload["plan"]["steps"][0]["at"] = "not-a-date"
            elif bad == "team":
                payload["team"] = "team_debit"
            await conn.execute("update sim_events set payload=%s where id=%s", (Jsonb(payload), event[0]))
        await conn.commit()
        await sim.conn.close()
        restored = Simulator(dsn=seeded)
        try:
            await restored.load_state()
            with pytest.raises(TeamPlanError):
                await restored.step(1)
            assert restored.rng.dump_state() == state and restored.clock.sim_time == clock
            assert (
                await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()
            ) == (0,)
            assert (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone()) == (clock,)
        finally:
            await restored.conn.close()


@pytest.mark.asyncio
async def test_sigkill_before_due_recovers_exact_plan_rng_and_real_take_time(seeded, monkeypatch, tmp_path):
    import asyncio
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from .test_behavior_process import stop, wait_ready

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        _, _, _, sim = await ready(conn, monkeypatch, seeded)
        await sim.conn.close()
    root = Path(__file__).resolve().parents[2]
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
    env.update(
        APP_ENV="test",
        ENV_FILE="/dev/null",
        LLM_PROVIDER="mock",
        LLM_RECORD="0",
        LOG_JSONL="false",
        DATABASE_URL=seeded,
        DATABASE_URL_TEST=seeded,
        PYTHONPATH=str(root) + os.pathsep + str(root.parent),
    )
    children, handles = [], []

    def spawn(name, phase):
        output = tmp_path / (name + ".json")
        handle = (tmp_path / (name + ".log")).open("w")
        handles.append(handle)
        child = subprocess.Popen(
            [sys.executable, str(root / "tests/fixtures/team_plan_process.py")],
            env=env | {"TEAM_PLAN_PHASE": phase, "TEAM_PLAN_OUTPUT": str(output)},
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        children.append(child)
        return child, output

    try:
        prime, a = spawn("prime", "prime")
        before = await asyncio.to_thread(wait_ready, a, prime)
        prime.kill()
        await asyncio.to_thread(prime.wait, timeout=10)
        assert prime.returncode == -9
        recovered, b = spawn("recovered", "recover")
        await asyncio.to_thread(recovered.wait, timeout=30)
        assert recovered.returncode == 0
        after = json.loads(b.read_text())
        assert after["stage"] == "complete"
        assert {key: before[key] for key in ("plans", "rng", "clock")} == {
            key: after[key] for key in ("plans", "rng", "clock")
        }
        take = next(step for plan in before["plans"].values() for step in plan["steps"] if step["action"] == "take")
        assert after["action"] == "take"
        assert dt.datetime.fromisoformat(after["action_sim"]) == dt.datetime.fromisoformat(take["at"])
        (tmp_path / "proof.json").write_text(
            json.dumps(
                {"sigkill_returncode": -9, "plan_equal": True, "rng_equal": True, "native_take_time_equal": True},
                indent=2,
            )
        )
    finally:
        for child in children:
            await asyncio.to_thread(stop, child)
        for handle in handles:
            handle.close()


@pytest.mark.asyncio
async def test_concurrent_enrollment_is_single_native_fact(seeded, monkeypatch):
    import asyncio

    from app.sim.team_plans import ensure_runtime

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await setup(conn, monkeypatch, seeded)
        await conn.execute("delete from sim_events where run_id=%s and event_type='team.runtime_started'", (run,))
        await conn.commit()

        async def enroll():
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as worker:
                await ensure_runtime(worker, run, now)
                await worker.commit()

        await asyncio.wait_for(asyncio.gather(enroll(), enroll()), 10)
        assert (
            await (
                await conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='team.runtime_started'", (run,)
                )
            ).fetchone()
        ) == (1,)
        await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["duplicate", "version"])
async def test_bad_runtime_marker_refuses_before_generators(seeded, monkeypatch, bad):
    from app.sim.team_plans import TeamPlanError

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, now, sim = await ready(conn, monkeypatch, seeded)
        if bad == "duplicate":
            await conn.execute(
                'insert into sim_events(run_id,event_type,payload,sim_time) values(%s,\'team.runtime_started\',\'{"event_type":"team.runtime_started","version":1}\',%s)',
                (run, now),
            )
        else:
            await conn.execute(
                "update sim_events set payload=jsonb_set(payload,'{version}','2') where run_id=%s and event_type='team.runtime_started'",
                (run,),
            )
        await conn.commit()
        before = sim.rng.dump_state()
        with pytest.raises(TeamPlanError, match="team_runtime_marker_invalid"):
            await sim.step(1)
        assert sim.rng.dump_state() == before and sim.clock.sim_time == now
        assert (await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        await sim.conn.close()


@pytest.mark.asyncio
async def test_autocommit_cannot_split_plan_from_rng_transaction(seeded):
    from app.sim.team_plans import TeamPlanError, ensure_runtime

    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
        with pytest.raises(TeamPlanError, match="общая транзакция"):
            await ensure_runtime(conn, 1, dt.datetime.now(dt.UTC))


@pytest.mark.asyncio
async def test_legacy_release_without_plan_does_not_guess_pending_regression(seeded, monkeypatch):
    from app.sim.team_plans import TeamPlanError

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, _, sim = await ready(conn, monkeypatch, seeded)
        await sim.step(1)
        take = next(step.at for step in sim.world.team_emulator.plans[incident].steps if step.action == "take")
        await sim.step((take - sim.clock.sim_time).total_seconds() / 60)
        before = sim.rng.dump_state()
        # Только отрицательная legacy fixture: факт release существует, план/регрессия неизвестны.
        await conn.execute(
            "insert into team_actions(run_id,incident_id,team_code,action,payload,action_sim) values(%s,%s,'team_deposits','release','{}',%s)",
            (run, incident, take),
        )
        await conn.execute(
            "delete from sim_events where run_id=%s and event_type in ('team.plan','team.runtime_started')", (run,)
        )
        await conn.commit()
        await sim.conn.close()
        restored = Simulator(dsn=seeded)
        try:
            await restored.load_state()
            with pytest.raises(TeamPlanError, match="legacy_team_pending_unknown"):
                await restored.step(1)
            assert restored.rng.dump_state() == before and restored.clock.sim_time == take
        finally:
            await restored.conn.close()


@pytest.mark.asyncio
async def test_clarify_and_resume_before_next_due_restore_from_native_facts_without_draw(seeded, monkeypatch):
    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import update_incident

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, _, sim = await ready(conn, monkeypatch, seeded)
        await conn.execute(
            "update teams set speed_profile=jsonb_set(speed_profile,'{p_clarify}','1') where code='team_deposits'"
        )
        await conn.commit()
        await sim.step(1)
        clarify = next(step.at for step in sim.world.team_emulator.plans[incident].steps if step.action == "clarify")
        await sim.step((clarify - sim.clock.sim_time).total_seconds() / 60)
        expected = _plan_blob(sim.world.team_emulator.plans[incident])
        assert expected["paused_after_clarify"] and not expected["resumed"]
        state = sim.rng.dump_state()
        await sim.conn.close()
        resumed = Simulator(dsn=seeded)
        await resumed.load_state()
        await resumed._ensure_world()
        assert _plan_blob(resumed.world.team_emulator.plans[incident]) == expected
        assert resumed.rng.dump_state() == state
        await conn.rollback()
        await update_incident(
            ToolContext(conn, run_id=run, agent_run_id=0, sim_time=clarify, llm_source="mock"),
            incident,
            "in_progress",
            "synthetic actual client reply",
        )
        await conn.commit()
        await resumed.step(1)
        expected = _plan_blob(resumed.world.team_emulator.plans[incident])
        assert expected["resumed"]
        state = resumed.rng.dump_state()
        actions = await (
            await conn.execute("select id,action,action_sim from team_actions where run_id=%s order by id", (run,))
        ).fetchall()
        await resumed.conn.close()
        final = Simulator(dsn=seeded)
        try:
            await final.load_state()
            await final._ensure_world()
            assert _plan_blob(final.world.team_emulator.plans[incident]) == expected
            assert final.rng.dump_state() == state
            assert (
                await (
                    await conn.execute(
                        "select id,action,action_sim from team_actions where run_id=%s order by id", (run,)
                    )
                ).fetchall()
                == actions
            )
        finally:
            await final.conn.close()


@pytest.mark.asyncio
async def test_stale_builder_reuses_committed_native_plan_without_rng_redraw(seeded, monkeypatch):
    from types import SimpleNamespace

    from psycopg.types.json import Jsonb

    from app.sim.events import EventBus
    from app.sim.rng import SimRng
    from app.sim.teams import TeamEmulator

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, now, sim = await ready(conn, monkeypatch, seeded)
        initial = sim.rng.dump_state()
        await sim.conn.close()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as other:
            rng, stale_rng = SimRng(1), SimRng(1)
            rng.load_state(initial)
            stale_rng.load_state(initial)
            first = TeamEmulator(rng, conn, EventBus(conn), run)
            stale = TeamEmulator(stale_rng, other, EventBus(other), run)
            await first.load()
            await stale.load()
            assert first.plans == stale.plans == {}
            await first.tick(now, SimpleNamespace(active_faults=[]))
            await conn.execute("update sim_state set rng_state=%s where id=1", (Jsonb(rng.dump_state()),))
            await conn.commit()
            await stale.tick(now, SimpleNamespace(active_faults=[]))
            await other.commit()
            assert _plan_blob(stale.plans[incident]) == _plan_blob(first.plans[incident])
            assert stale_rng.dump_state() == initial and rng.dump_state() != initial
            assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone()) == (
                rng.dump_state(),
            )
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_events where run_id=%s and event_type='team.plan'", (run,)
                    )
                ).fetchone()
            ) == (1,)
            assert (
                await (await conn.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()
            ) == (0,)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["string", "empty"])
async def test_corrupt_legacy_action_snapshot_refuses_without_rebuilding(seeded, monkeypatch, bad):
    from psycopg.types.json import Jsonb

    from app.sim.team_plans import TeamPlanError

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, _, sim = await ready(conn, monkeypatch, seeded)
        await sim.step(1)
        take = next(step.at for step in sim.world.team_emulator.plans[incident].steps if step.action == "take")
        await sim.step((take - sim.clock.sim_time).total_seconds() / 60)
        state = sim.rng.dump_state()
        await conn.execute(
            "update team_actions set payload=jsonb_set(payload,'{plan}',%s) where run_id=%s",
            (Jsonb("unknown" if bad == "string" else {}), run),
        )
        await conn.commit()
        before = await (
            await conn.execute("select id,payload from team_actions where run_id=%s order by id", (run,))
        ).fetchall()
        await sim.conn.close()
        restored = Simulator(dsn=seeded)
        try:
            await restored.load_state()
            with pytest.raises(TeamPlanError, match="legacy_team_plan_invalid"):
                await restored.step(1)
            assert restored.rng.dump_state() == state and restored.clock.sim_time == take
            assert (
                await (
                    await conn.execute("select id,payload from team_actions where run_id=%s order by id", (run,))
                ).fetchall()
                == before
            )
        finally:
            await restored.conn.close()


@pytest.mark.asyncio
async def test_synthetic_dump_clone_preserves_native_plan_rng_and_first_action(seeded, monkeypatch, tmp_path):
    import shutil
    import subprocess
    import uuid

    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    dump, restore = shutil.which("pg_dump"), shutil.which("pg_restore")
    if not dump or not restore:
        pytest.skip("нужны native PostgreSQL16 dump/restore для synthetic clone proof")
    assert all(" 16." in subprocess.check_output([tool, "--version"], text=True) for tool in (dump, restore))
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, incident, _, sim = await ready(conn, monkeypatch, seeded)
        await sim.step(1)
        expected, state = _plan_blob(sim.world.team_emulator.plans[incident]), sim.rng.dump_state()
        take = next(step.at for step in sim.world.team_emulator.plans[incident].steps if step.action == "take")
        clock = sim.clock.sim_time
        await sim.conn.close()
    name = "cx_team_plan_clone_" + uuid.uuid4().hex[:12]
    admin = make_conninfo(dsn(seeded), dbname="postgres")
    clone = make_conninfo(dsn(seeded), dbname=name)
    archive = tmp_path / "synthetic-team-plan.dump"
    # Только отдельная synthetic reference copy, не операторский bank baseline:
    # полный dump сохраняет одинаковый контракт disposable клона, включая private test schemas.
    result = subprocess.run(
        [dump, "-Fc", "--no-owner", "--no-acl", "-f", str(archive), dsn(seeded)], capture_output=True, timeout=60
    )
    assert result.returncode == 0, "synthetic pg_dump failed"
    with psycopg.connect(admin, autocommit=True) as ac:
        ac.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    restored = None
    try:
        result = subprocess.run(
            [restore, "--no-owner", "--no-acl", "--dbname", clone, str(archive)], capture_output=True, timeout=60
        )
        assert result.returncode == 0, "synthetic pg_restore failed"
        restored = Simulator(dsn=clone)
        await restored.load_state()
        # Та же controlled workload, что ready(): генерируем только team execution.
        restored._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0)
        await restored._ensure_world()
        assert restored.run_id == run and restored.clock.sim_time == clock
        assert restored.rng.dump_state() == state
        assert _plan_blob(restored.world.team_emulator.plans[incident]) == expected
        await restored.step((take - clock).total_seconds() / 60)
        assert restored.rng.dump_state() == state
        assert (
            await (
                await restored.conn.execute(
                    "select action,action_sim from team_actions where run_id=%s order by id", (run,)
                )
            ).fetchall()
        ) == [("take", take)]
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as original:
            assert (
                await (await original.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()
            ) == (clock, state)
            assert (
                await (await original.execute("select count(*) from team_actions where run_id=%s", (run,))).fetchone()
            ) == (0,)
    finally:
        if restored and restored.conn:
            await restored.conn.close()
        with psycopg.connect(admin, autocommit=True) as ac:
            ac.execute(sql.SQL("drop database {}").format(sql.Identifier(name)))
