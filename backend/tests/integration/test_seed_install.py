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
        connection.execute("drop schema if exists langgraph cascade; drop schema public cascade; create schema public")
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


def test_installer_seed_requires_reload_before_native_start(migrated_db, monkeypatch):
    """Сохраняем старую память до seed: reload исправляет только installer boundary."""
    import importlib.util
    import io
    import json

    from app.sim.engine import StaleSimulatorError

    spec = importlib.util.spec_from_file_location("install_seed_state_native", ROOT / "scripts/install_seed_state.py")
    assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    url = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists langgraph cascade; drop schema public cascade; create schema public")
    env = {**os.environ, "DATABASE_URL": migrated_db}
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
    )
    assert migrated.returncode == 0, migrated.stderr

    def fingerprints():
        with psycopg.connect(url) as conn:
            tables = conn.execute(
                "select schemaname,tablename from pg_tables where schemaname in ('public','langgraph','llm_runtime','channel_runtime') order by 1,2"
            ).fetchall()
            return {
                (schema, table): conn.execute(
                    sql.SQL(
                        "select count(*),md5(coalesce(string_agg(md5(to_jsonb(t)::text),'' order by md5(to_jsonb(t)::text)),'')) from {}.{} t"
                    ).format(sql.Identifier(schema), sql.Identifier(table))
                ).fetchone()
                for schema, table in tables
            }

    async def lifecycle():
        loaded = Simulator(seed=42, dsn=migrated_db)
        replacement = None
        current = loaded
        monkeypatch.setattr(
            helper.urllib.request, "urlopen", lambda *_args, **_kw: io.StringIO(json.dumps(current.state_dict()))
        )
        try:
            await loaded.load_state()
            assert loaded.run_id is None
            seeded = subprocess.run(
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
                capture_output=True,
                text=True,
            )
            assert seeded.returncode == 0, seeded.stderr
            with psycopg.connect(url) as conn:
                persisted = conn.execute(
                    "select s.current_run_id,s.sim_time,s.seed,s.running,r.kind,r.status from sim_state s join sim_runs r on r.id=s.current_run_id where s.id=1"
                ).fetchone()
            assert persisted and persisted[0] is not None and persisted[2:] == (42, False, "baseline", "completed")
            before = fingerprints()
            assert helper.check_state(url, "http://owned-test.invalid/sim/state") == 3
            with pytest.raises(StaleSimulatorError):
                await loaded.control("start")
            assert loaded.run_id is None
            await loaded.shutdown()
            replacement = Simulator(seed=42, dsn=migrated_db)
            current = replacement
            await replacement.load_state()
            assert replacement.run_id == persisted[0] and replacement.clock.sim_time == persisted[1]
            assert helper.check_state(url, "http://owned-test.invalid/sim/state") == 0
            assert fingerprints() == before  # Reload не меняет банк, часы, raw RNG или operational ledger.
            await replacement.control("start", label="Первый запуск после installer seed")
            initial_time = replacement.clock.sim_time
            for _ in range(100):
                if replacement.clock.sim_time > initial_time:
                    break
                await asyncio.sleep(0.05)
            assert replacement.clock.running and replacement.clock.sim_time > initial_time
            task = replacement._task
            assert task and not task.done()
            assert helper.check_state(url, "http://owned-test.invalid/sim/state") == 0
            assert replacement._task is task and replacement.clock.running  # Совпавший active World не прерывается.
            await replacement.control("pause")
            await replacement.step(480)
            assert replacement.stats["ops"] > 0 and replacement.stats["signals"] > 0
        finally:
            if replacement is not None:
                await replacement.shutdown()
            await loaded.shutdown()

    asyncio.run(lifecycle())
