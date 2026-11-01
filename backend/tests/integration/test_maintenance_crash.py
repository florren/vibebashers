"""T-040: падение настоящего процесса не открывает origins после потери PG session."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import psycopg

from app.config import get_settings
from app.sim import baseline
from app.sim.maintenance_control import MaintenanceControl
from app.sim.maintenance_db import LOCK


async def test_os_process_crash_after_sql_restore_requires_explicit_lifespan_recovery(seeded, tmp_path, monkeypatch):
    from app import main
    from app.public_chat import create_public_app

    directory = tmp_path / "archive"
    directory.mkdir()
    monkeypatch.setattr(baseline, "baseline_dir", lambda: directory)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: directory / "runs")
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await baseline.dump(conn, "lite")
    code = """
import asyncio,os
from pathlib import Path
import psycopg
from app.sim import baseline
from app.sim.maintenance import MaintenanceCoordinator
from app.sim.maintenance_db import DatabaseBoundary
from app.sim.maintenance_control import MaintenanceControl
async def run():
 directory=Path(os.environ['T040_ARCHIVE_DIR'])
 baseline.baseline_dir=lambda:directory
 baseline.runs_export_dir=lambda:directory/'runs'
 def crash(*args): os._exit(23)
 baseline._run_csi_repair=crash
 c=MaintenanceCoordinator(boundary=DatabaseBoundary(),control=MaintenanceControl())
 async def action(job):
  async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://')) as conn:
   return await baseline.restore(conn,profile='lite',job_id=job)
 await c.restore(action)
asyncio.run(run())
"""
    env = {**os.environ, "DATABASE_URL": seeded, "T040_ARCHIVE_DIR": str(directory)}
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await asyncio.wait_for(child.communicate(), 30)
    assert child.returncode == 23
    control = MaintenanceControl()
    assert control.read()["phase"] == "restoring"
    # Процесс и PG lease уже исчезли; блокировка public теперь только durable.
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        assert (await (await conn.execute("select pg_try_advisory_lock_shared(%s,%s)", LOCK)).fetchone())[0]
        await conn.execute("select pg_advisory_unlock_shared(%s,%s)", LOCK)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_public_app()), base_url="http://personal"
    ) as public:
        assert (await public.get("/api/personal/session")).status_code == 503
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAIN", "mock")
    monkeypatch.setenv("PROFILE", "lite")
    get_settings.cache_clear()
    prepare = AsyncMock(wraps=main._prepare_runtime_profiles)
    backfill = AsyncMock(wraps=main._abs_backfill)
    monkeypatch.setattr(main, "_prepare_runtime_profiles", prepare)
    monkeypatch.setattr(main, "_abs_backfill", backfill)
    app = main.create_app()
    async with main.lifespan(app):
        assert app.state.maintenance.phase == "failed"
        assert app.state.agent is None and app.state.twins is None and not app.state.runtime_components
        prepare.assert_not_awaited()
        backfill.assert_not_awaited()
        assert app.state.sim.conn is None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://main") as client:
            assert (await client.get("/api/health")).status_code == 503
            assert (await client.get("/api/sim/baseline")).status_code == 200
            response = await client.post("/api/sim/baseline/restore")
            assert response.status_code == 202, response.text
        assert control.read()["phase"] == "idle" and app.state.maintenance.phase == "ready"
        prepare.assert_awaited_once()
        backfill.assert_awaited_once()
        assert app.state.agent is not None and app.state.twins is not None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_public_app()), base_url="http://personal"
        ) as public:
            assert (await public.get("/api/personal/health")).status_code == 200
    second = main.create_app()
    async with main.lifespan(second):
        assert second.state.maintenance.phase == "ready"
        assert second.state.agent is not None and second.state.twins is not None
        assert control.read()["phase"] == "idle"
    get_settings.cache_clear()


async def test_seed_before_main_initializes_only_missing_marker_under_exclusive(seeded, conn):
    control = MaintenanceControl()
    control.path.unlink()
    before = conn.execute("select count(*) from clients").fetchone()[0]
    root = Path(__file__).resolve().parents[3]
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        str(root / "scripts/seed/run.py"),
        "--if-needed",
        "--profile",
        "lite",
        cwd=root,
        env={**os.environ, "DATABASE_URL": seeded},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(child.communicate(), 20)
    assert child.returncode == 0 and control.read()["phase"] == "idle"
    assert conn.execute("select count(*) from clients").fetchone()[0] == before
    control.write("failed", "past-job")
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        str(root / "scripts/seed/run.py"),
        "--if-needed",
        "--profile",
        "lite",
        cwd=root,
        env={**os.environ, "DATABASE_URL": seeded},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(child.communicate(), 20)
    assert child.returncode == 4 and control.read()["phase"] == "failed"
    assert conn.execute("select count(*) from clients").fetchone()[0] == before
