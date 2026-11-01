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

    async def close(self):
        self.closed = True


@pytest.fixture
def wired(monkeypatch):
    app = create_app()
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
            lambda: TwinService.react(actor, None, 1),
            lambda: Simulator.step(actor, 1),
        ):
            with pytest.raises(MaintenanceBusy):
                await call()
