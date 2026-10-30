"""T-272: только добавление недостающих CSI, старые записи/решения и часы неизменны."""

from __future__ import annotations

import importlib
from pathlib import Path

import psycopg
import pytest

from tests.helpers import dsn
from tests.integration.test_hitl_continuity import make_case
from tests.integration.test_seed_install import snapshot

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def test_additive_csi_repair_is_atomic_and_idempotent(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    repair = importlib.import_module("scripts.seed.repair_csi")
    rid = conn.execute("select (value->>'run_id')::bigint from settings where key='seed_done'").fetchone()[0]
    conn.execute(
        "delete from ingest_messages where signal_id in(select id from signals where run_id=%s and channel_code='csi_survey')",
        (rid,),
    )
    conn.execute("delete from signals where run_id=%s and channel_code='csi_survey'", (rid,))
    seed_done = conn.execute("select to_jsonb(s) from settings s where key='seed_done'").fetchone()[0]
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "repair-existing-decision", cid)
    conn.execute(
        "update human_decisions set decision='reject',decided_by='operator',decided_at=now() where id=%s",
        (case["hid"],),
    )
    conn.execute("update sim_state set current_run_id=%s,running=false where id=1", (case["rid"],))
    before = snapshot(conn)
    audit_max = conn.execute("select coalesce(max(id),0) from db_activity_log").fetchone()[0]
    state = conn.execute("select to_jsonb(s) from sim_state s").fetchone()[0]
    with psycopg.connect(dsn(seeded)) as ac:
        dry = repair.repair(ac, apply=False)
    assert dry["before"] == 440 and len(dry["missing_csi"]) == 40 and dry["added"] == 0
    assert snapshot(conn) == before
    with psycopg.connect(dsn(seeded)) as ac:
        result = repair.repair(ac, apply=True)
    assert result["added"] == 40 and result["after"] == 480 and result["run_id"] == rid
    assert (
        conn.execute(
            "select count(*) from signals where id=any(%s) and run_id=%s and channel_code='csi_survey' and origin='sim' and status='closed'",
            (result["signal_ids"], rid),
        ).fetchone()[0]
        == 40
    )
    after = snapshot(conn)
    for table in before:
        if table not in ("signals", "ingest_messages", "csi_responses", "settings", "db_activity_log"):
            assert after[table] == before[table], table
    assert conn.execute("select to_jsonb(s) from sim_state s").fetchone()[0] == state
    assert conn.execute("select to_jsonb(s) from settings s where key='seed_done'").fetchone()[0] == seed_done
    # Старые сигналы сохранены: сравниваем digest после исключения только новых ID.
    old_count, old_hash = conn.execute(
        "select count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' order by row_to_json(t)::text),'')) from (select * from signals where not(id=any(%s)))t",
        (result["signal_ids"],),
    ).fetchone()
    assert (old_count, old_hash) == before["signals"]
    assert (
        conn.execute(
            "select count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' order by row_to_json(t)::text),'')) from (select * from db_activity_log where id<=%s)t",
            (audit_max,),
        ).fetchone()
        == before["db_activity_log"]
    )
    stable = snapshot(conn)
    with psycopg.connect(dsn(seeded)) as ac:
        assert repair.repair(ac, apply=True)["added"] == 0
    assert snapshot(conn) == stable


def test_csi_repair_failure_rolls_back_and_rejects_unrelated_gaps(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    repair = importlib.import_module("scripts.seed.repair_csi")
    rid = conn.execute("select (value->>'run_id')::bigint from settings where key='seed_done'").fetchone()[0]
    conn.execute(
        "delete from ingest_messages where signal_id in(select id from signals where run_id=%s and channel_code='csi_survey')",
        (rid,),
    )
    conn.execute("delete from signals where run_id=%s and channel_code='csi_survey'", (rid,))
    before = snapshot(conn)
    real = repair.create_signal_sync
    calls = 0

    def fail_after_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise repair.RepairError("synthetic failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(repair, "create_signal_sync", fail_after_first)
    with pytest.raises(repair.RepairError):
        with psycopg.connect(dsn(seeded)) as ac:
            repair.repair(ac, apply=True)
    assert snapshot(conn) == before
    conn.execute("delete from signals where run_id=%s and channel_code='call'", (rid,))
    with pytest.raises(repair.RepairError, match="вне CSI"):
        with psycopg.connect(dsn(seeded)) as ac:
            repair.repair(ac)
