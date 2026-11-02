"""T262: native Mock/HITL и настоящий XLSX→normalizer→scoped membership."""

import asyncio
import copy

import psycopg
import pytest
from psycopg.rows import dict_row, tuple_row

from app.agent.graph import process_signal
from app.sim import scenario_acceptance as acceptance
from app.sim import scenarios as sc
from app.sim.runs import create_run
from tests.helpers import MOCK_PROFILE, dsn, mock_chain


async def prepared_run(conn, scenario_id="csi_and_branches"):
    scenario = sc.get(scenario_id)
    await sc.ensure_registered(conn, scenario)
    clock = (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone())["sim_time"]
    run = await create_run(
        conn, kind="scenario", scenario_id=scenario_id, label="T262 isolated proof", seed=42, sim_time=clock
    )
    await conn.execute("update sim_runs set status='paused' where id=%s", (run,))
    await conn.execute("update sim_state set running=false where id=1")
    await conn.commit()
    return run


async def scalar(conn, sql, args=()):
    return next(iter((await (await conn.execute(sql, args)).fetchone()).values()))


def test_actual_xlsx_exact_retry_reconnect_and_extra_unknown_denominator(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as conn:
            run = await prepared_run(conn)
            before = await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone()
            plan = await acceptance.reserve_csi(conn, run)
            first = await acceptance.prepare_csi(conn, run)
            assert (first["imported"]["accepted"], first["registered"]["members"], first["registered"]["visits"]) == (
                301,
                300,
                2400,
            )
            result = await acceptance.evaluate_native(conn, sc.get("csi_and_branches"), run)
            assert result["counts"]["native_passed"] and not result["passed"]
            assert await scalar(conn, "select count(*) from agent_runs where sim_run_id=%s", (run,)) == 0
            assert await scalar(conn, "select count(*) from ledger_entries where run_id=%s", (run,)) == 0
            assert (
                await (await conn.execute("select sim_time,rng_state from sim_state where id=1")).fetchone() == before
            )
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as conn:
            again = await acceptance.reserve_csi(conn, run)
            assert {k: v for k, v in again.items() if k != "prepared"} == {
                k: v for k, v in plan.items() if k != "prepared"
            }
            retry = await acceptance.prepare_csi(conn, run)
            assert retry["xlsx_sha256"] == first["xlsx_sha256"]
            assert retry["imported"]["duplicates"] == 301 and retry["imported"]["accepted"] == 0
            assert retry["registered"]["status"] == "existing"
            bases = await acceptance._free_bases(conn)
            assert plan["extra_id_base"] not in bases and plan["id_base"] not in bases
            second = await prepared_run(conn)
            second_plan = await acceptance.reserve_csi(conn, second)
            assert {second_plan["id_base"], second_plan["extra_id_base"]}.isdisjoint(
                {plan["id_base"], plan["extra_id_base"]}
            )
            assert await scalar(conn, "select count(*) from signals where run_id=%s", (run,)) == 301
            with pytest.raises(acceptance.PreparationError, match="current paused"):
                await acceptance.prepare_csi(conn, run)

    asyncio.run(check())


def test_import_failure_rolls_back_but_reservation_survives(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as conn:
            run = await prepared_run(conn)
            plan = await acceptance.reserve_csi(conn, run)
            # Нативный отказ последней строки после300 успешных INSERT внутри одного TX.
            await conn.execute("select set_config('t262.fail_id',%s,false)", (f"CSI-{plan['extra_id_base'] + 1:06d}",))
            await conn.execute(
                "create function t262_reject() returns trigger language plpgsql as $$ begin if NEW.csi_no=current_setting('t262.fail_id',true) then raise exception 'T262 injected late failure'; end if; return NEW; end $$"
            )
            try:
                await conn.execute(
                    "create trigger t262_reject before insert on csi_responses for each row execute function t262_reject()"
                )
                with pytest.raises(psycopg.errors.RaiseException, match="late failure"):
                    await acceptance.prepare_csi(conn, run)
                assert await scalar(conn, "select count(*) from signals where run_id=%s", (run,)) == 0
                assert await acceptance.reserve_csi(conn, run) == plan
            finally:
                await conn.execute("drop trigger if exists t262_reject on csi_responses")
                await conn.execute("drop function if exists t262_reject()")
            assert (await acceptance.prepare_csi(conn, run))["imported"]["accepted"] == 301

    asyncio.run(check())


def test_native_mock_legal_wait_and_independent_product_facade(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            run = await prepared_run(conn, "cabinet_red_words_report")
            at = (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone())["sim_time"]
            injected = await sc.inject(conn, sc.get("cabinet_red_words_report"), run, sim_time=at)
            await conn.commit()
            conn.row_factory = tuple_row
            for row in injected:
                state = await process_signal(conn, signal_id=row["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
                assert not state["errors"], state["errors"]
            conn.row_factory = dict_row
            result = await acceptance.evaluate_native(conn, sc.get("cabinet_red_words_report"), run)
            assert result["counts"]["native_passed"] and not result["passed"], result
            assert result["counts"]["not_verified"] == 2
            unknown = copy.deepcopy(sc.get("cabinet_red_words_report"))
            unknown["expected"]["unimplemented_ui_check"] = True
            result = await acceptance.evaluate_native(conn, unknown, run)
            assert not result["passed"] and result["counts"]["not_verified"] == 3
            refs = [
                r["public_id"]
                for r in await (await conn.execute("select public_id from signals where run_id=%s", (run,))).fetchall()
            ]
            return run, refs

    run, refs = asyncio.run(check())
    import httpx
    from fastapi.testclient import TestClient
    from scripts.acceptance_check import verify_reads

    from app.main import create_app
    from tests.integration.test_cabinet_api import fingerprint

    app = create_app()
    with TestClient(app), psycopg.connect(dsn(seeded)) as sql:
        before = fingerprint(sql)

        async def read():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                checks = await verify_reads(http, "cabinet_red_words_report", run, None, refs)
                assert all(c["ok"] for c in checks), checks

        asyncio.run(read())
        assert fingerprint(sql) == before


def test_two_connections_reserve_same_plan_before_import(seeded):
    async def check():
        async with (
            await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as first,
            await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as second,
        ):
            run = await prepared_run(first)
            left, right = await asyncio.gather(acceptance.reserve_csi(first, run), acceptance.reserve_csi(second, run))
            assert left == right
            assert left["id_base"] != left["extra_id_base"]
            before = await scalar(first, "select count(*) from signals where run_id=%s", (run,))
            await first.execute(
                "update sim_runs set settings_snapshot=jsonb_set(settings_snapshot,'{t262_inputs,xlsx_sha256}',%s::jsonb) where id=%s",
                ('"' + "0" * 64 + '"', run),
            )
            with pytest.raises(acceptance.PreparationError, match="hash"):
                await acceptance.prepare_csi(first, run)
            assert await scalar(first, "select count(*) from signals where run_id=%s", (run,)) == before == 0

    asyncio.run(check())


def test_actual_run_api_and_existing_csi_branch_reads(seeded):
    import httpx
    from fastapi.testclient import TestClient
    from scripts.acceptance_check import verify_reads

    from app.agent.runner import AgentService
    from app.main import create_app
    from app.sim.engine import Simulator

    app = create_app()
    with TestClient(app) as client:
        # APP_ENV=test не поднимает listeners; настоящий сервис подключён явно.
        app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
        sim = app.state.sim = Simulator(dsn=seeded)
        client.portal.call(sim.load_state)
        response = client.post("/api/scenarios/csi_and_branches/run", json={})
        assert response.status_code == 202, response.text
        run = response.json()["run"]["id"]
        with psycopg.connect(dsn(seeded)) as conn:
            at, running, current = conn.execute(
                "select sim_time,running,current_run_id from sim_state where id=1"
            ).fetchone()
            assert not running and current == run
            plan = conn.execute("select settings_snapshot->'t262_inputs' from sim_runs where id=%s", (run,)).fetchone()[
                0
            ]
            assert plan["prepared"] and plan["clock"] == at.isoformat()
            assert (
                conn.execute(
                    "select count(*) from sim_events where run_id=%s and event_type='signal.received'", (run,)
                ).fetchone()[0]
                == 301
            )

        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                result = await verify_reads(http, "csi_and_branches", run, plan)
                assert all(row["ok"] for row in result), result

        asyncio.run(check())
        client.portal.call(sim.shutdown)


def test_generic_import_and_preparation_do_not_deadlock_on_native_run_fk(seeded):
    """Generic importer уже держит csi_import; preparation не блокирует его FK insert."""
    from app.ingest.csi import import_rows

    async def check():
        async with (
            await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as importer,
            await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as preparer,
        ):
            run = await prepared_run(preparer)
            plan = await acceptance.reserve_csi(preparer, run)
            row = acceptance._input(plan)[2][0]
            task = None
            try:
                async with importer.transaction():
                    await importer.execute("select pg_advisory_xact_lock(hashtext('csi_import'))")
                    task = asyncio.create_task(acceptance.prepare_csi(preparer, run))
                    for _ in range(200):
                        blockers = await scalar(importer, "select pg_blocking_pids(%s)", (preparer.info.backend_pid,))
                        if importer.info.backend_pid in blockers:
                            break
                        await asyncio.sleep(0.01)
                    else:
                        raise AssertionError("preparation не достигла native csi_import barrier")
                    report = await asyncio.wait_for(import_rows(importer, [row]), timeout=5)
                    assert report["accepted"] == 1
                result = await asyncio.wait_for(task, timeout=15)
                assert result["imported"]["duplicates"] == 1 and result["imported"]["accepted"] == 300
                assert result["registered"]["members"] == 300
            finally:
                if task is not None:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())
