"""T-248: SQL границы sample provenance, normalizer-native CSI signals."""

import datetime as dt
from pathlib import Path

import psycopg
import pytest

from app.ingest.normalizer import from_csi
from app.ingest.sync_bridge import create_signal_sync
from tests.helpers import dsn

ROOT = Path(__file__).resolve().parents[3]
START = dt.datetime(2026, 11, 9, 9, tzinfo=dt.timezone(dt.timedelta(hours=3)))
END = START + dt.timedelta(hours=8)


@pytest.fixture
def sample(seeded):
    with psycopg.connect(dsn(seeded)) as conn:
        run_id = conn.execute("SELECT current_run_id FROM sim_state WHERE id=1").fetchone()[0]
        branch, line = conn.execute("SELECT id,product_line_codes[1] FROM branches WHERE code='0042'").fetchone()
        payload = {
            "csi_no": "CSI-030001",
            "complaint_ru": "Учебная жалоба: сотрудник отвечал невежливо.",
            "branch_code": "0042",
            "employee_public_id": "EMP-00001",
            "received_at": (START + dt.timedelta(hours=1)).isoformat(),
            "wait_min": 12,
            "redirects": 1,
        }
        signal_id = create_signal_sync(conn, from_csi(payload), run_id=run_id, sim_time=START)["signal_id"]
        cohort_id = conn.execute(
            "INSERT INTO csi_cohorts(run_id,dataset_code,dataset_digest,directory_digest,visits_digest,members_digest,branch_id,product_line_code,"
            "window_start,window_end,is_synthetic,member_count) VALUES(%s,'csi_test_v1',%s,%s,%s,%s,%s,%s,%s,%s,true,1) RETURNING id",
            (run_id, "a" * 64, "b" * 64, "c" * 64, "d" * 64, branch, line, START, END),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO csi_cohort_visits(cohort_id,run_id,wait_bucket,redirects_bucket,visits) VALUES(%s,%s,'5-15','1',20)",
            (cohort_id, run_id),
        )
        conn.commit()
        yield conn, run_id, branch, signal_id, cohort_id


def add_member(conn, run_id, branch, signal, cohort, *, when=START + dt.timedelta(hours=1), wait="5-15"):
    conn.execute(
        "INSERT INTO csi_cohort_members(signal_id,cohort_id,run_id,branch_id,response_at,wait_bucket,redirects_bucket) "
        "VALUES(%s,%s,%s,%s,%s,%s,'1')",
        (signal, cohort, run_id, branch, when, wait),
    )


def test_native_membership_audit_and_idempotent_migration(sample):
    conn, run_id, branch, signal, cohort = sample
    add_member(conn, run_id, branch, signal, cohort)
    conn.commit()
    for _ in range(2):
        conn.execute((ROOT / "contracts/db/migrations/0020_csi_cohorts.sql").read_text())
    assert conn.execute("SELECT count(*) FROM csi_cohort_members WHERE cohort_id=%s", (cohort,)).fetchone() == (1,)
    audit = conn.execute(
        "SELECT table_name,run_id,pk,summary FROM db_activity_log WHERE table_name LIKE 'csi_cohort%' ORDER BY id"
    ).fetchall()
    assert {r[0] for r in audit} == {"csi_cohorts", "csi_cohort_visits", "csi_cohort_members"}
    assert all(r[1] == run_id and r[2] and set(r[3]) == {"changed_fields"} for r in audit)
    with conn.transaction():
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                add_member(conn, run_id, branch, signal, cohort)


def test_mismatched_owner_branch_bucket_and_time_fail_before_membership(sample):
    conn, run_id, branch, signal, cohort = sample
    foreign_run = conn.execute(
        "INSERT INTO sim_runs(kind,label,seed,started_sim) VALUES('live','CSI isolation fixture',42,%s) RETURNING id",
        (START,),
    ).fetchone()[0]
    other_branch = conn.execute("SELECT id FROM branches WHERE code='0107'").fetchone()[0]
    cases = [
        {"run_id": foreign_run},
        {"branch": other_branch},
        {"when": START - dt.timedelta(microseconds=1)},
        {"when": END},
        {"wait": "15-30"},
    ]
    for override in cases:
        values = {"run_id": run_id, "branch": branch, "signal": signal, "cohort": cohort, **override}
        with pytest.raises(psycopg.IntegrityError):
            with conn.transaction():
                add_member(conn, **values)
        assert conn.execute("SELECT count(*) FROM csi_cohort_members WHERE cohort_id=%s", (cohort,)).fetchone() == (0,)
    add_member(conn, run_id, branch, signal, cohort, when=START)
    assert conn.execute("SELECT count(*) FROM csi_cohort_members WHERE cohort_id=%s", (cohort,)).fetchone() == (1,)


def test_snapshot_header_and_nonnegative_visits_are_enforced(sample):
    conn, run_id, branch, signal, cohort = sample
    add_member(conn, run_id, branch, signal, cohort)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE csi_cohorts SET member_count=2 WHERE id=%s", (cohort,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO csi_cohort_visits(cohort_id,run_id,wait_bucket,redirects_bucket,visits) VALUES(%s,%s,'0-5','0',-1)",
                (cohort, run_id),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE csi_cohort_visits SET visits=21 WHERE cohort_id=%s", (cohort,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "UPDATE csi_cohort_members SET response_at=%s WHERE signal_id=%s",
                (START + dt.timedelta(hours=2), signal),
            )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO csi_cohort_visits(cohort_id,run_id,wait_bucket,redirects_bucket,visits) VALUES(%s,%s,'0-5','0',20)",
                (cohort, run_id + 1000000),
            )
    assert conn.execute("SELECT member_count FROM csi_cohorts WHERE id=%s", (cohort,)).fetchone() == (1,)
