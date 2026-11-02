"""T-040: реальная ASGI граница и lifecycle фоновых writers без внешних вызовов."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api import sim as api
from app.main import create_app
from app.sim import baseline
from app.sim.maintenance import MaintenanceBusy


class Connection:
    closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def transaction(self):
        return self

    async def close(self):
        self.closed = True


@pytest.fixture
def wired(monkeypatch):
    app = create_app()
    app.state.maintenance.boundary = None
    app.state.maintenance.control = None
    connection = Connection()
    sim = SimpleNamespace(
        clock=SimpleNamespace(running=False),
        run_status="stopped",
        conn=connection,
        connect=AsyncMock(return_value=connection),
        control=AsyncMock(),
        reload_after_restore=AsyncMock(),
    )
    app.state.sim = sim
    app.state.maintenance_park = AsyncMock()
    app.state.maintenance_resume = AsyncMock()
    monkeypatch.setattr(baseline, "info", lambda: {"available": True})
    monkeypatch.setattr(baseline, "preflight_restore", AsyncMock())
    # Real maintenance cancellation/leases; binding has real-PG regressions.
    monkeypatch.setattr(api, "capture", AsyncMock())
    monkeypatch.setattr(api, "_conn", AsyncMock(return_value=connection))
    return app, sim


async def test_real_http_cancel_waits_owned_process_headers_and_reload(wired, monkeypatch):
    app, sim = wired
    started = threading.Event()
    release = threading.Event()
    stages = []

    def process():
        started.set()
        assert release.wait(5)

    async def restore(conn, **kwargs):
        await asyncio.to_thread(process)
        stages.extend(["headers", "CSI"])
        return kwargs["job_id"]

    monkeypatch.setattr(baseline, "restore", restore)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        caller = asyncio.create_task(client.post("/api/sim/baseline/restore"))
        assert await asyncio.to_thread(started.wait, 3)
        caller.cancel()
        await asyncio.sleep(0)
        assert app.state.maintenance.phase == "restoring"
        assert (await client.get("/api/health")).status_code == 503
        assert (await client.get("/api/sim/baseline")).status_code == 200
        assert (await client.post("/api/sim/baseline/restore")).status_code == 409
        assert not stages and not sim.reload_after_restore.await_count
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
    assert stages == ["headers", "CSI"] and app.state.maintenance.phase == "ready"
    sim.reload_after_restore.assert_awaited_once()
    app.state.maintenance_resume.assert_awaited_once()


async def test_real_http_failed_closed_explicit_retry(wired, monkeypatch):
    app, sim = wired
    restore = AsyncMock(side_effect=baseline.BaselineToolingError("CSI repair failed"))
    monkeypatch.setattr(baseline, "restore", restore)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/sim/baseline/restore")).status_code == 409
        assert app.state.maintenance.phase == "failed"
        assert (await client.get("/api/health")).status_code == 503
        assert (await client.get("/api/sim/baseline")).status_code == 200
        restore.side_effect = None
        restore.return_value = "retried"
        assert (await client.post("/api/sim/baseline/restore")).json() == {"job_id": "retried"}
    assert app.state.maintenance.phase == "ready"
    sim.reload_after_restore.assert_awaited_once()


@pytest.mark.parametrize("kind", ["audio", "seed"])
async def test_real_http_busy_protected_actor_keeps_work_alive(wired, monkeypatch, kind):
    app, _ = wired
    entered = asyncio.Event()
    release = asyncio.Event()

    async def active():
        async with app.state.maintenance.operation(kind):
            entered.set()
            await release.wait()

    actor = asyncio.create_task(active())
    await entered.wait()
    restore = AsyncMock()
    monkeypatch.setattr(baseline, "restore", restore)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/sim/baseline/restore")
        assert response.status_code == 409
    assert not actor.done()
    restore.assert_not_awaited()
    app.state.maintenance_park.assert_not_awaited()
    release.set()
    await actor


async def test_drain_timeout_is_before_any_exports(wired, monkeypatch):
    app, _ = wired
    app.state.maintenance.drain_timeout = 0.01
    entered = asyncio.Event()
    release = asyncio.Event()

    async def active():
        async with app.state.maintenance.operation("agent"):
            entered.set()
            await release.wait()

    actor = asyncio.create_task(active())
    await entered.wait()
    restore = AsyncMock()
    monkeypatch.setattr(baseline, "restore", restore)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/sim/baseline/restore")).status_code == 409
    assert app.state.maintenance.phase == "ready"
    restore.assert_not_awaited()
    app.state.maintenance_park.assert_not_awaited()
    release.set()
    await actor


async def test_real_actor_entrypoints_reject_before_db_access():
    from app.agent.runner import AgentService
    from app.sim.engine import Simulator
    from app.sim.maintenance import MaintenanceCoordinator
    from app.sim.twins import TwinService

    c = MaintenanceCoordinator()
    c.phase = "restoring"
    # Неполные self намеренно: любой вход в тело до admission немедленно упадёт.
    actor = object()
    with c.bind():
        for call in (
            lambda: AgentService._recover(actor),
            lambda: AgentService._process(actor, 1, None),
            lambda: AgentService.resume(actor, 1),
            lambda: AgentService._expire_hitl(actor, None),
            lambda: AgentService._wake_followups(actor, None),
            lambda: AgentService.validate_recovery(actor, 1, None),
            lambda: AgentService.recover_run(actor, 1, None),
            lambda: AgentService._recover_one(actor, 1, None),
            lambda: AgentService._recover_timers(actor, 1, None, []),
            lambda: TwinService.react(actor, None, 1),
            lambda: Simulator.step(actor, 1),
        ):
            with pytest.raises(MaintenanceBusy):
                await call()


def test_real_audio_ws_is_protected_until_disconnect(wired, monkeypatch):
    from fastapi.testclient import TestClient

    app, sim = wired
    restore = AsyncMock()
    monkeypatch.setattr(baseline, "restore", restore)
    with TestClient(app) as client:
        app.state.sim = sim
        with client.websocket_connect("/ws/audio/1"):
            assert any(row.kind == "audio" for row in app.state.maintenance._records.values())
            assert client.post("/api/sim/baseline/restore").status_code == 409
            assert app.state.maintenance.phase == "ready"
            restore.assert_not_awaited()
            app.state.maintenance_park.assert_not_awaited()


async def test_agent_stop_waits_timer_cleanup_and_clears_identity_cache():
    from app.agent.runner import AgentService
    from app.sim.maintenance import MaintenanceCoordinator

    c = MaintenanceCoordinator()
    service = AgentService(None, None)
    entered = asyncio.Event()
    cleaned = []

    async def timer():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.append("closed")

    with c.bind():
        task = service._background(timer(), name="maintenance-proof-timer")
    service._by_signal[17] = task
    await entered.wait()
    await service.stop()
    assert cleaned == ["closed"] and task.cancelled()
    assert not service._inflight and not service._by_signal


async def test_runtime_cache_instances_are_replaced_before_daemon_admission(monkeypatch):
    from app import main
    from app.db import session
    from app.sim.maintenance import MaintenanceCoordinator

    c = MaintenanceCoordinator()
    c.phase = "reloading"
    c._ready.clear()
    old_agent = SimpleNamespace(stop=AsyncMock(), enabled=False)
    old_twins = SimpleNamespace(stop=AsyncMock())
    old_bench = SimpleNamespace(stop=AsyncMock())
    fake = SimpleNamespace(
        state=SimpleNamespace(
            maintenance=c,
            runtime_components={"agent", "twins"},
            agent=old_agent,
            twins=old_twins,
            bench=old_bench,
            llm_chain=None,
            llm_profile=None,
            sim=SimpleNamespace(clock=SimpleNamespace(running=False), shutdown=AsyncMock()),
        )
    )
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(session, "get_engine", lambda: engine)
    await main._park_runtime(fake)
    await main._resume_runtime(fake)
    assert fake.state.agent is not old_agent and fake.state.twins is not old_twins
    assert fake.state.bench is not old_bench and fake.state.agent.enabled is False
    old_agent.stop.assert_awaited_once()
    old_twins.stop.assert_awaited_once()
    old_bench.stop.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    # Новые listener/twin/cache не касаются БД до открытия ready.
    assert not c._records
    await fake.state.agent.stop()
    await fake.state.twins.stop()


async def test_recovery_children_are_reserved_until_checkpoint_and_timer_cleanup(monkeypatch):
    from app.agent import runner
    from app.sim.maintenance import MaintenanceCoordinator

    c = MaintenanceCoordinator()
    service = runner.AgentService(None, None)
    entered = asyncio.Event()
    release = asyncio.Event()
    touched = []

    class RecoveryConnection(Connection):
        async def execute(self, sql, *args):
            rows = [(41, 7)] if "select ar.id,ar.signal_id" in sql else []
            return SimpleNamespace(fetchall=AsyncMock(return_value=rows))

        async def commit(self):
            pass

    monkeypatch.setattr(service, "_conn", AsyncMock(return_value=RecoveryConnection()))

    async def recovering(*args):
        entered.set()
        await release.wait()
        touched.append("checkpoint")

    monkeypatch.setattr(service, "_recover_one", recovering)

    async def expiry(*args, **kwargs):
        touched.append("timers")

    monkeypatch.setattr(runner, "expire_hitl", expiry)
    monkeypatch.setattr(runner, "wake_due_followups", AsyncMock())
    with c.bind():
        await service.recover_run(1, None)
    assert len(c._records) == 2
    await entered.wait()

    async def action(job):
        touched.append("restore")
        return job

    restoring = asyncio.create_task(c.restore(action))
    await asyncio.sleep(0)
    assert c.phase == "draining" and touched == []
    release.set()
    await restoring
    assert touched == ["checkpoint", "timers", "restore"]
    assert not service._inflight and not service._by_signal
