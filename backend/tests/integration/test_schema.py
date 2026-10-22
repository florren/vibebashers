"""T-005/T-199/T-221: схема по контракту на живой PostgreSQL — миграции, идемпотентность, триггеры, представления, downgrade."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def alembic(*args: str, url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT / "backend",
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )


def test_head_is_0003_and_74_tables(conn, migrated_db) -> None:
    assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0003"
    n = conn.execute(
        "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name<>'alembic_version'"
    ).fetchone()[0]
    assert n == 74
    views = {r[0] for r in conn.execute("select table_name from information_schema.views where table_schema='public'")}
    assert {"v_tickets", "v_map_zones", "v_region_heat", "v_run_counters", "v_feed_latency"} <= views


def test_migrations_sql_are_idempotent(conn) -> None:
    for name in ("0002_brd_contours.sql", "0003_additional_tz.sql"):
        sql = (ROOT / "contracts/db/migrations" / name).read_text(encoding="utf-8")
        conn.execute(sql)
        conn.execute(sql)
    n = conn.execute(
        "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name<>'alembic_version'"
    ).fetchone()[0]
    assert n == 74


def test_alembic_check_no_drift(migrated_db) -> None:
    r = alembic("check", url=migrated_db)
    assert r.returncode == 0, r.stderr[-1500:]


def test_db_activity_trigger_writes_log(conn) -> None:
    conn.execute(
        "insert into channels (code, name_ru, name_en, identifies_client) values ('chat','Чат','Chat',true) on conflict do nothing"
    )
    run_id = conn.execute(
        "insert into sim_runs (kind, label, seed, started_sim) values ('live','t',1,now()) returning id"
    ).fetchone()[0]
    before = conn.execute("select count(*) from db_activity_log where table_name='signals'").fetchone()[0]
    conn.execute(
        "insert into signals (run_id, channel_code, text, received_sim, origin) values (%s, 'chat', 'тест', now(), 'sim')",
        (run_id,),
    )
    after = conn.execute("select count(*) from db_activity_log where table_name='signals'").fetchone()[0]
    assert after == before + 1


def test_views_execute(conn) -> None:
    for v in (
        "v_tickets",
        "v_map_zones",
        "v_region_heat",
        "v_run_counters",
        "v_feed_latency",
        "v_compliance_by_employee",
    ):
        conn.execute(f"select * from {v} limit 1").fetchall()


def test_downgrade_0003_and_upgrade_again(migrated_db, conn) -> None:
    r = alembic("downgrade", "0002", url=migrated_db)
    assert r.returncode == 0, r.stderr[-1500:]
    n = conn.execute(
        "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name<>'alembic_version'"
    ).fetchone()[0]
    assert n == 69
    r = alembic("upgrade", "head", url=migrated_db)
    assert r.returncode == 0, r.stderr[-1500:]
    n = conn.execute(
        "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' and table_name<>'alembic_version'"
    ).fetchone()[0]
    assert n == 74
