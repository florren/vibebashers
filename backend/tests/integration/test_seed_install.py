"""T-270: повтор установки не меняет БД/снимок, первичные ошибки имеют явный код."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from app.sim import baseline
from app.sim.engine import Simulator

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def test_first_install_after_backend_bootstrap_generates_events(migrated_db):
    """Health уже доступен и sim_state существует, но первичный банк ещё не заполнен."""
    url = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("drop schema public cascade; create schema public")
    env = {**os.environ, "DATABASE_URL": migrated_db}
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env=env,
        text=True,
        capture_output=True,
    )
    assert migrated.returncode == 0, migrated.stderr

    async def bootstrap():
        sim = Simulator(seed=42, dsn=migrated_db)
        try:
            await sim.load_state()
        finally:
            await sim.shutdown()

    asyncio.run(bootstrap())
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/seed/run.py"),
            "--if-needed",
            "--profile",
            "lite",
            "--clients",
            "200",
            "--seed",
            "42",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "seed_existing_incomplete" not in result.stderr
    with psycopg.connect(url) as connection:
        assert connection.execute("select count(*) from clients").fetchone()[0] == 200
        assert connection.execute("select value->>'seed' from settings where key='seed_done'").fetchone()[0] == "42"

    async def generate():
        sim = Simulator(seed=42, dsn=migrated_db)
        try:
            await sim.load_state()
            await sim.control("start", label="Проверка чистой установки", start_paused=True)
            # Проверяем полный рабочий день: двухчасовой случайный поток может
            # законно не содержать жалоб при неизменных вероятностях генерации.
            await sim.step(480)
            assert sim.stats["ops"] > 0 and sim.stats["signals"] > 0
            return sim.run_id
        finally:
            await sim.shutdown()

    run_id = asyncio.run(generate())
    with psycopg.connect(url) as connection:
        assert connection.execute("select count(*) from operations where run_id=%s", (run_id,)).fetchone()[0] > 0
        assert connection.execute("select count(*) from signals where run_id=%s", (run_id,)).fetchone()[0] > 0
        assert connection.execute("select count(*) from sim_events where run_id=%s", (run_id,)).fetchone()[0] > 0


def snapshot(conn):
    tables = conn.execute("select tablename from pg_tables where schemaname='public' order by tablename").fetchall()
    return {
        name: conn.execute(
            sql.SQL(
                "select count(*), md5(coalesce(string_agg(row_to_json(t)::text,'' order by row_to_json(t)::text),'')) from {} t"
            ).format(sql.Identifier(name))
        ).fetchone()
        for (name,) in tables
    }


def test_reinstall_preserves_all_existing_data_and_baseline(seeded, conn, monkeypatch):
    # Имитируем расширение справочника после первоначального seed: старую историю не подменяем.
    conn.execute(
        "insert into channels(code,name_ru,name_en,identifies_client) values ('test_new_channel','Тест','Test',false)"
    )
    before = snapshot(conn)
    dump = ROOT / "data/baseline/lite.dump"
    dump_before = dump.read_bytes()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/seed/run.py"), "--if-needed", "--profile", "demo", "--seed", "99"],
        env={**os.environ, "DATABASE_URL": seeded},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "seed_existing_preserved" in result.stderr and "coverage_ok" in result.stderr and "False" in result.stderr
    assert "baseline_dump_start" not in result.stderr
    monkeypatch.syspath_prepend(str(ROOT))
    seed = importlib.import_module("scripts.seed.run")
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setattr(sys, "argv", ["run.py", "--if-needed", "--profile", "lite"])
    assert seed.main() == 0
    assert snapshot(conn) == before
    assert dump.read_bytes() == dump_before


@pytest.mark.parametrize("failure,expected", [("coverage", 2), ("baseline", 3), ("tools", 3)])
def test_seed_reports_real_failure(seeded, conn, monkeypatch, failure, expected):
    monkeypatch.syspath_prepend(str(ROOT))
    seed = importlib.import_module("scripts.seed.run")
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setattr(sys, "argv", ["run.py", "--profile", "lite"])
    before = conn.execute("select value from settings where key='seed_done'").fetchone()
    if failure == "coverage":
        monkeypatch.setattr(
            seed,
            "compute_coverage",
            lambda *a, **k: {"sla_cells_ok": False, "signal_combos_missing": ["test"], "sla_cells": {}},
        )
    else:

        def fail(*a, **k):
            raise baseline.BaselineToolingError("synthetic tooling failure")

        monkeypatch.setattr(baseline, "check_tools" if failure == "tools" else "dump_for_connection", fail)
    all_before = snapshot(conn) if failure == "tools" else None
    assert seed.main() == expected
    assert conn.execute("select value from settings where key='seed_done'").fetchone() == before
    if all_before is not None:
        assert snapshot(conn) == all_before


@pytest.mark.parametrize("marker", ["missing", "invalid_run"])
def test_partial_seed_is_not_automatically_replaced(seeded, conn, monkeypatch, marker):
    monkeypatch.syspath_prepend(str(ROOT))
    seed = importlib.import_module("scripts.seed.run")
    conn.execute("delete from settings where key='seed_done'")
    if marker == "invalid_run":
        conn.execute("insert into settings(key,value) values ('seed_done','{\"run_id\":99999999}')")
    before = snapshot(conn)
    assert seed.preserve_existing(conn.cursor(), "lite") == 4
    assert snapshot(conn) == before
