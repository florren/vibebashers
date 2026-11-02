"""T-248: атомарный native import/registration, без моделей и внешнего I/O."""

import asyncio
import copy

import psycopg
import pytest
from psycopg.rows import dict_row

from app.analytics import csi_cohorts
from app.ingest.csi import Row, import_rows
from app.sim.csi_scoped_corpus import generate_scoped
from app.sim.runs import create_run
from tests.helpers import dsn


async def sample_run(conn):
    clock = await (await conn.execute("SELECT sim_time FROM sim_state WHERE id=1")).fetchone()
    return await create_run(
        conn, kind="live", label="CSI synthetic cohort fixture", seed=42, sim_time=clock["sim_time"]
    )


async def scalar(conn, sql, args=()):
    row = await (await conn.execute(sql, args)).fetchone()
    return next(iter(row.values()))


def test_native_registration_exact_retry_and_no_model_or_money_effects(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            run_id = await sample_run(conn)
            clock_before = await (await conn.execute("SELECT sim_time,rng_state FROM sim_state WHERE id=1")).fetchone()
            first = await csi_cohorts.install_scoped_sample(conn)
            assert (first["accepted"], first["duplicates"], first["members"], first["visits"]) == (300, 0, 300, 2400)
            assert first["status"] == "registered"
            audit_before = await scalar(conn, "SELECT count(*) FROM db_activity_log")
            again = await csi_cohorts.install_scoped_sample(conn)
            assert again["digest"] == first["digest"] and again["status"] == "existing"
            assert (again["accepted"], again["duplicates"]) == (0, 300)
            assert await scalar(conn, "SELECT count(*) FROM db_activity_log") == audit_before
            assert await scalar(conn, "SELECT count(*) FROM csi_cohorts WHERE run_id=%s", (run_id,)) == 10
            assert await scalar(conn, "SELECT count(*) FROM csi_cohort_members WHERE run_id=%s", (run_id,)) == 300
            assert await scalar(conn, "SELECT sum(visits) FROM csi_cohort_visits WHERE run_id=%s", (run_id,)) == 2400
            assert (
                await scalar(
                    conn, "SELECT count(*) FROM v_csi_cohort_integrity WHERE run_id=%s AND is_complete", (run_id,)
                )
                == 10
            )
            assert (
                await (await conn.execute("SELECT sim_time,rng_state FROM sim_state WHERE id=1")).fetchone()
                == clock_before
            )
            assert await scalar(conn, "SELECT count(*) FROM agent_runs WHERE sim_run_id=%s", (run_id,)) == 0
            assert await scalar(conn, "SELECT count(*) FROM ledger_entries WHERE run_id=%s", (run_id,)) == 0
            # Направление в cohort — явно объявленный sample факт. Классификация
            # агента не подменяется этим import и по-прежнему отсутствует.
            assert (
                await scalar(
                    conn, "SELECT count(*) FROM signals WHERE run_id=%s AND product_line_code IS NOT NULL", (run_id,)
                )
                == 0
            )

    asyncio.run(check())


def test_changed_existing_payload_rolls_back_new_rows_preserving_original(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            run_id = await sample_run(conn)
            row = copy.deepcopy(generate_scoped()["complaints"][0])
            row["complaint_ru"] = "Учебная жалоба: исходная независимая запись, не reviewed corpus."
            report = await import_rows(conn, [Row(1, row, {})])
            assert report["accepted"] == 1
            await conn.commit()
            await conn.execute("SELECT 1")
            with pytest.raises(csi_cohorts.CohortRegistrationError, match="иным accepted payload"):
                await csi_cohorts.install_scoped_sample(conn)
            assert await scalar(conn, "SELECT count(*) FROM signals WHERE run_id=%s", (run_id,)) == 1
            assert await scalar(conn, "SELECT count(*) FROM csi_cohorts WHERE run_id=%s", (run_id,)) == 0
            assert await scalar(conn, "SELECT text FROM signals WHERE run_id=%s", (run_id,)) == row["complaint_ru"]

    asyncio.run(check())


def test_foreign_run_is_not_reassigned_and_explicit_new_namespace_is_isolated(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            first_run = await sample_run(conn)
            await csi_cohorts.install_scoped_sample(conn)
            await conn.commit()
            second_run = await sample_run(conn)
            with pytest.raises(csi_cohorts.CohortRegistrationError, match="чужим run"):
                await csi_cohorts.install_scoped_sample(conn)
            assert await scalar(conn, "SELECT count(*) FROM csi_cohorts WHERE run_id=%s", (second_run,)) == 0
            result = await csi_cohorts.install_scoped_sample(conn, id_base=30300)
            assert result["accepted"] == 300 and result["status"] == "registered"
            assert await scalar(conn, "SELECT count(*) FROM signals WHERE run_id=%s", (first_run,)) == 300
            assert await scalar(conn, "SELECT count(*) FROM signals WHERE run_id=%s", (second_run,)) == 300

    asyncio.run(check())


def test_deleted_denominator_is_not_repaired_silently(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            await sample_run(conn)
            await csi_cohorts.install_scoped_sample(conn)
            await conn.execute("DELETE FROM csi_cohort_visits WHERE id=(SELECT min(id) FROM csi_cohort_visits)")
            await conn.commit()
            await conn.execute("SELECT 1")
            with pytest.raises(csi_cohorts.CohortRegistrationError, match="denominator snapshot"):
                await csi_cohorts.install_scoped_sample(conn)
            assert await scalar(conn, "SELECT count(*) FROM csi_cohort_visits") == 119
            assert await scalar(conn, "SELECT count(*) FROM v_csi_cohort_integrity WHERE NOT is_complete") == 1

    asyncio.run(check())


def test_storage_failure_rolls_back_all_native_imports(seeded, monkeypatch):
    async def fail(*args):
        raise RuntimeError("synthetic failure after native import")

    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            run_id = await sample_run(conn)
            before = await scalar(conn, "SELECT count(*) FROM db_activity_log")
            with pytest.raises(RuntimeError, match="synthetic failure"):
                await csi_cohorts.install_scoped_sample(conn)
            assert await scalar(conn, "SELECT count(*) FROM signals WHERE run_id=%s", (run_id,)) == 0
            assert await scalar(conn, "SELECT count(*) FROM csi_cohorts WHERE run_id=%s", (run_id,)) == 0
            assert await scalar(conn, "SELECT count(*) FROM db_activity_log") == before

    monkeypatch.setattr(csi_cohorts, "_native_members", fail)
    asyncio.run(check())
