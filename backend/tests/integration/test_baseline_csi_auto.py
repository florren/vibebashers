"""T-275: restore сам завершает CSI-ремонт до готовности baseline, без повторных данных."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import psycopg
import pytest

from app.config import get_settings
from app.sim import baseline
from tests.helpers import dsn
from tests.integration.test_hitl_continuity import make_case
from tests.integration.test_seed_install import snapshot

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


@pytest.fixture
def restore_env(seeded, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path / "runs")
    try:
        yield tmp_path
    finally:
        get_settings.cache_clear()


async def archive(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
        await baseline.dump(ac, "lite")


async def restore(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
        return await baseline.restore(ac, profile="lite")


@pytest.fixture
def archived_case(seeded, conn):
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    return make_case(conn, seeded, "archived-human-decision", cid)


async def test_old_archive_is_repaired_before_finished_and_never_duplicates(
    seeded, conn, restore_env, monkeypatch, archived_case
):
    monkeypatch.syspath_prepend(str(ROOT))
    coverage = importlib.import_module("scripts.seed.coverage")
    rid = conn.execute("select (value->>'run_id')::bigint from settings where key='seed_done'").fetchone()[0]
    conn.execute(
        "delete from ingest_messages where signal_id in(select id from signals where channel_code='csi_survey')"
    )
    conn.execute("delete from signals where channel_code='csi_survey'")
    with conn.cursor() as cur:
        assert coverage.compute_coverage(cur, rid)["signal_combos_covered"] == 440
    case = archived_case
    conn.execute(
        "update human_decisions set decision='reject',decided_by='operator',decided_at=now() where id=%s",
        (case["hid"],),
    )
    before = snapshot(conn)
    max_audit = conn.execute("select max(id) from db_activity_log").fetchone()[0]
    await archive(seeded)
    archive_bytes = {p.name: p.read_bytes() for p in restore_env.iterdir() if p.is_file()}
    reports = []
    real_repair = baseline._run_csi_repair

    def track_repair(*args):
        report = real_repair(*args)
        reports.append(report)
        return report

    monkeypatch.setattr(baseline, "_run_csi_repair", track_repair)
    for _ in range(2):
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as listener:
            await listener.execute("listen runs")
            assert await restore(seeded)
            messages = [json.loads(n.payload)["type"] async for n in listener.notifies(timeout=0.1)]
        assert messages == ["baseline_restore_started", "baseline_restore_finished"]
        assert reports[-1]["before"] == 440 and reports[-1]["added"] == 40 and reports[-1]["after"] == 480
        assert conn.execute("select count(*),count(distinct csi_no) from csi_responses").fetchone() == (40, 40)
        assert conn.execute(
            "select distinct status,origin,run_id from signals where channel_code='csi_survey'"
        ).fetchall() == [("closed", "sim", rid)]
        after = snapshot(conn)
        for table in before:
            if table not in ("signals", "ingest_messages", "csi_responses", "db_activity_log", "settings", "sim_runs"):
                assert after[table] == before[table], table
        for table, limit in (("signals", reports[-1]["signal_ids"][0] - 1), ("db_activity_log", max_audit)):
            old = conn.execute(
                f"select count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' order by row_to_json(t)::text),'')) from(select * from {table} where id<=%s)t",
                (limit,),
            ).fetchone()
            assert old == before[table], table
        assert conn.execute("select value->>'signal_combos_covered' from settings where key='coverage'").fetchone() == (
            "480",
        )
        assert {p.name: p.read_bytes() for p in restore_env.iterdir() if p.is_file()} == archive_bytes
        stable = snapshot(conn)
        assert real_repair(dsn(seeded), baseline._csi_repair_script())["added"] == 0
        assert snapshot(conn) == stable


async def test_current_archive_restore_is_noop_for_csi(seeded, conn, restore_env):
    await archive(seeded)
    before = snapshot(conn)
    await restore(seeded)
    after = snapshot(conn)
    for table in before:
        if table != "db_activity_log":
            assert after[table] == before[table], table


async def test_non_csi_gap_prevents_finished_event(seeded, conn, restore_env):
    conn.execute("delete from signals where channel_code='chat' and origin='sim'")
    await archive(seeded)
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as listener:
        await listener.execute("listen runs")
        with pytest.raises(baseline.BaselineToolingError, match="вне CSI"):
            await restore(seeded)
        messages = [json.loads(n.payload)["type"] async for n in listener.notifies(timeout=0.1)]
    assert messages == ["baseline_restore_started"]
