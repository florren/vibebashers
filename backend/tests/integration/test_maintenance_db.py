"""T-040: реальная PG fairness, межпроцессный lifetime и cooperating CLI seed."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

from app.sim.maintenance import MaintenanceBusy, MaintenanceCoordinator
from app.sim.maintenance_db import LOCK, DatabaseBoundary, public_operation


async def queued(conn):
    async def wait():
        while True:
            row = await (
                await conn.execute(
                    "select exists(select 1 from pg_locks where locktype='advisory' and database=(select oid from pg_database where datname=current_database()) and classid=%s and objid=%s and mode='ExclusiveLock' and not granted)",
                    LOCK,
                )
            ).fetchone()
            if row[0]:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), 3)


async def test_shared_http_drains_and_queued_exclusive_refuses_new_public_admission(seeded):
    import psycopg

    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")
    boundary = DatabaseBoundary(dsn=dsn)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as inspector:
        async with public_operation(dsn):
            exclusive = asyncio.create_task(boundary.acquire())
            await queued(inspector)
            assert not exclusive.done()
            with pytest.raises(MaintenanceBusy):
                async with public_operation(dsn):
                    pytest.fail("новый HTTP обошёл ожидающий exclusive")
        await exclusive
        try:
            with pytest.raises(MaintenanceBusy):
                async with public_operation(dsn):
                    pytest.fail("exclusive не удержан")
        finally:
            await boundary.release()
        async with public_operation(dsn):
            pass


async def test_bounded_global_wait_is_before_effects_and_does_not_cancel_public(seeded):
    c = MaintenanceCoordinator(boundary=DatabaseBoundary(dsn=seeded, timeout_ms=30))
    touched = []

    async def action(job):
        touched.append(job)
        return job

    async with public_operation(seeded):
        with pytest.raises(MaintenanceBusy, match="Public HTTP/CLI seed"):
            await c.restore(action)
        assert not touched and c.phase == "ready"
        async with public_operation(seeded):
            pass


async def test_parent_cancel_retains_global_exclusive_until_supervised_reload(seeded):
    import psycopg

    boundary = DatabaseBoundary(dsn=seeded)
    c = MaintenanceCoordinator(boundary=boundary)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def action(job):
        started.set()
        await finish.wait()
        return job

    async with await psycopg.AsyncConnection.connect(
        seeded.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as inspector:
        async with public_operation(seeded):
            caller = asyncio.create_task(c.restore(action))
            await queued(inspector)
            caller.cancel()
            await asyncio.sleep(0)
            assert c.phase == "draining" and not started.is_set()
        await asyncio.wait_for(started.wait(), 3)
        try:
            with pytest.raises(MaintenanceBusy):
                async with public_operation(seeded):
                    pytest.fail("cancel освободил глобальный gate")
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
    assert c.phase == "ready" and boundary.conn is None
    async with public_operation(seeded):
        pass


async def test_failed_closed_retains_global_lock_and_explicit_retry_releases(seeded):
    boundary = DatabaseBoundary(dsn=seeded)
    c = MaintenanceCoordinator(boundary=boundary)

    async def failed(_):
        raise RuntimeError("synthetic CSI failure")

    try:
        with pytest.raises(RuntimeError, match="CSI"):
            await c.restore(failed)
        assert c.phase == "failed" and boundary.conn is not None
        with pytest.raises(MaintenanceBusy):
            async with public_operation(seeded):
                pytest.fail("failed main пропустил personal")

        async def retry(job):
            return job

        await c.restore(retry)
        assert c.phase == "ready" and boundary.conn is None
        async with public_operation(seeded):
            pass
    finally:
        await boundary.release()


async def test_public_app_http_and_cli_seed_cooperate_without_modifying_data(seeded, conn):
    from app.public_chat import create_public_app

    boundary = DatabaseBoundary(dsn=seeded)
    before = conn.execute("select count(*) from clients").fetchone()[0]
    await boundary.acquire()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_public_app()), base_url="http://personal"
        ) as client:
            for path in ("/api/personal/health", "/api/personal/session"):
                response = await client.get(path)
                assert response.status_code == 503 and response.headers["content-type"] == "application/problem+json"
        root = Path(__file__).resolve().parents[3]
        process = await asyncio.create_subprocess_exec(
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
        stdout, stderr = await process.communicate()
        assert process.returncode == 4 and b"seed_maintenance_busy" in stderr
        assert conn.execute("select count(*) from clients").fetchone()[0] == before
    finally:
        await boundary.release()


async def test_global_gate_survives_real_restore_headers_csi_and_parent_cancel(seeded, tmp_path, monkeypatch):
    import threading

    import psycopg

    from app.sim import baseline

    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path / "runs")
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await baseline.dump(conn, "lite")
    boundary = DatabaseBoundary(dsn=dsn)
    c = MaintenanceCoordinator(boundary=boundary)
    restore_started = threading.Event()
    release_restore = threading.Event()
    headers_started = asyncio.Event()
    release_headers = asyncio.Event()
    csi_started = threading.Event()
    release_csi = threading.Event()
    original_restore = baseline._run_pg_restore
    original_headers = baseline._restore_sim_runs
    original_csi = baseline._run_csi_repair
    stages = []

    def restoring(*args):
        restore_started.set()
        assert release_restore.wait(10)
        original_restore(*args)
        stages.append("SQL")

    async def headers(*args):
        headers_started.set()
        await release_headers.wait()
        await original_headers(*args)
        stages.append("headers")

    def csi(*args):
        csi_started.set()
        assert release_csi.wait(10)
        result = original_csi(*args)
        stages.append("CSI")
        return result

    monkeypatch.setattr(baseline, "_run_pg_restore", restoring)
    monkeypatch.setattr(baseline, "_restore_sim_runs", headers)
    monkeypatch.setattr(baseline, "_run_csi_repair", csi)

    async def action(job):
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            return await baseline.restore(conn, profile="lite", job_id=job)

    async def reload():
        stages.append("reload")

    async def blocked():
        with pytest.raises(MaintenanceBusy):
            async with public_operation(dsn):
                pytest.fail("gate открыт между фазами")

    caller = asyncio.create_task(c.restore(action, resume=reload))
    try:
        assert await asyncio.to_thread(restore_started.wait, 5)
        caller.cancel()
        await blocked()
        release_restore.set()
        await asyncio.wait_for(headers_started.wait(), 10)
        assert c.phase == "restoring"
        await blocked()
        release_headers.set()
        assert await asyncio.to_thread(csi_started.wait, 5)
        await blocked()
        release_csi.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert stages == ["SQL", "headers", "CSI", "reload"]
        assert c.phase == "ready" and boundary.conn is None
        async with public_operation(dsn):
            pass
    finally:
        release_restore.set()
        release_headers.set()
        release_csi.set()
        await asyncio.gather(caller, return_exceptions=True)
        await boundary.release()
