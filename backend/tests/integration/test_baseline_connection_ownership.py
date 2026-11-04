"""Baseline API не коммитит чужую native TX и удерживает conn до завершения export."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from app.api.sim import router
from app.sim import baseline, baseline_contract, engine
from app.sim.engine import Simulator
from app.sim.maintenance import MaintenanceCoordinator, MaintenanceMiddleware
from tests.helpers import dsn
from tests.integration.conftest import rebuild_schema


class ObservedLock:
    def __init__(self, lock, task_name, waiting):
        self.lock, self.task_name, self.waiting = lock, task_name, waiting

    async def __aenter__(self):
        if asyncio.current_task().get_name() == self.task_name and self.lock.locked():
            self.waiting.set()
        await self.lock.acquire()
        return self

    async def __aexit__(self, *_args):
        self.lock.release()


def application(sim):
    app = FastAPI()
    app.state.sim = sim
    coordinator = MaintenanceCoordinator()
    app.add_middleware(MaintenanceMiddleware, coordinator=coordinator)
    app.include_router(router)
    return app


async def visible_run(database_url, run_id):
    async with await psycopg.AsyncConnection.connect(dsn(database_url)) as observer:
        await observer.execute("set transaction read only")
        return (await (await observer.execute("select count(*) from sim_runs where id=%s", (run_id,))).fetchone())[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_baseline_waits_for_uncommitted_native_control_before_rechecking_active_run(
    migrated_db, tmp_path, monkeypatch, cancel
):
    rebuild_schema(migrated_db)
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    sim = Simulator(dsn=migrated_db)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    entered, release, waiting, dump_entered, dump_release = (asyncio.Event() for _ in range(5))
    sim._lock = ObservedLock(sim._lock, "baseline-during-control", waiting)
    original_create, original_fingerprint = engine.run_svc.create_run, baseline_contract.read
    created = {}

    async def blocked_create(conn, *args, **kwargs):
        run_id = await original_create(conn, *args, **kwargs)
        created["id"] = run_id
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        # SQL уже изменил native run/pointer, но control ещё не присвоил Python state и не сделал commit.
        entered.set()
        await release.wait()
        return run_id

    async def blocked_fingerprint(conn):
        value = await original_fingerprint(conn)
        # Старый dump уже выполнил initial commit. Останавливаем его до pg_dump/публикации архива.
        dump_entered.set()
        await dump_release.wait()
        return value

    monkeypatch.setattr(engine.run_svc, "create_run", blocked_create)
    monkeypatch.setattr(baseline_contract, "read", blocked_fingerprint)
    control = dump = None
    watchers = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(sim)), base_url="http://own.test") as http:
        try:
            control = asyncio.create_task(
                http.post("/api/sim/control", json={"action": "start", "label": "Native transaction owner"}),
                name="native-control-open-tx",
            )
            await asyncio.wait_for(entered.wait(), 10)
            assert await visible_run(migrated_db, created["id"]) == 0
            dump = asyncio.create_task(http.post("/api/sim/baseline"), name="baseline-during-control")
            watchers = [asyncio.create_task(waiting.wait()), asyncio.create_task(dump_entered.wait())]
            await asyncio.wait_for(asyncio.wait([*watchers, dump], return_when=asyncio.FIRST_COMPLETED), 10)
            # Отдельное подключение не должно видеть чужую TX до release её настоящего владельца.
            assert await visible_run(migrated_db, created["id"]) == 0, "baseline prematurely committed native control"
            assert waiting.is_set() and not dump_entered.is_set() and not dump.done()
            if cancel:
                dump.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await dump
                assert not control.done() and await visible_run(migrated_db, created["id"]) == 0
            release.set()
            response = await asyncio.wait_for(control, 10)
            assert response.status_code == 200, response.text
            if not cancel:
                response = await asyncio.wait_for(dump, 10)
                assert response.status_code == 409 and "активном запуске" in response.text
            assert await visible_run(migrated_db, created["id"]) == 1
            assert not list(tmp_path.iterdir())
        finally:
            if dump is not None and not dump.done():
                dump.cancel()
            if dump is not None:
                await asyncio.gather(dump, return_exceptions=True)
            release.set()
            dump_release.set()
            if control is not None:
                await asyncio.gather(control, return_exceptions=True)
            for watcher in watchers:
                watcher.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)
            if sim.conn:
                await sim.conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_baseline_owns_connection_through_real_export_and_cancellation(
    migrated_db, tmp_path: Path, monkeypatch, cancel
):
    rebuild_schema(migrated_db)
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    sim = Simulator(dsn=migrated_db)
    monkeypatch.setattr(sim, "_start_loop", lambda: None)
    await sim.load_state()
    entered, waiting = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    sim._lock = ObservedLock(sim._lock, "control-during-baseline", waiting)
    original_dump = baseline._run_pg_dump
    loop = asyncio.get_running_loop()

    def blocked_export(*args):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(20), "test export release missing"
        original_dump(*args)

    monkeypatch.setattr(baseline, "_run_pg_dump", blocked_export)
    dump = control = watcher = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(sim)), base_url="http://own.test") as http:
        try:
            dump = asyncio.create_task(http.post("/api/sim/baseline"), name="baseline-export-owner")
            await asyncio.wait_for(entered.wait(), 10)
            control = asyncio.create_task(
                http.post("/api/sim/control", json={"action": "start", "label": "Control after complete snapshot"}),
                name="control-during-baseline",
            )
            watcher = asyncio.create_task(waiting.wait())
            await asyncio.wait_for(asyncio.wait([watcher, control], return_when=asyncio.FIRST_COMPLETED), 10)
            assert waiting.is_set() and not control.done(), "control overlapped exported snapshot transaction"
            if cancel:
                dump.cancel()
                await asyncio.sleep(0)  # Доставить cancellation, не освобождая настоящий pg_dump worker.
                assert not dump.done() and not control.done()
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(dump, 15)
                assert not list(tmp_path.iterdir())
            else:
                response = await asyncio.wait_for(dump, 15)
                assert response.status_code == 202, response.text
                assert response.json()["available"]
                archive = Path(response.json()["path"])
                assert archive.is_file() and archive.stat().st_size > 0
                assert archive.with_suffix(".meta.json").is_file()
                assert archive.with_suffix(".dump.sha256").is_file()
            response = await asyncio.wait_for(control, 10)
            assert response.status_code == 200, response.text
            assert await visible_run(migrated_db, sim.run_id) == 1
        finally:
            release.set()
            if dump is not None and not dump.done():
                dump.cancel()
            await asyncio.gather(*[task for task in (dump, control) if task is not None], return_exceptions=True)
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if sim.conn:
                await sim.conn.close()
