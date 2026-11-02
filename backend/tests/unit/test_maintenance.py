"""T-040: детерминированные барьеры admission/drain, отмена и recovery без БД."""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.sim.maintenance import (
    MaintenanceBusy,
    MaintenanceCoordinator,
    MaintenanceMiddleware,
    spawn_writer,
    writer_lease,
)


async def phase(c, name):
    while c.phase != name:
        c._changed.clear()
        if c.phase != name:
            await asyncio.wait_for(c._changed.wait(), 2)


async def test_drain_precedes_exports_and_children_outlive_http():
    c = MaintenanceCoordinator()
    release = asyncio.Event()
    started = asyncio.Event()
    exported = asyncio.Event()

    async def child():
        async with writer_lease("child"):
            started.set()
            await release.wait()

    async def http():
        async with c.operation("http"):
            return spawn_writer(child(), kind="child")

    task = await asyncio.create_task(http())
    await started.wait()

    async def restore(job):
        exported.set()
        return job

    resetting = asyncio.create_task(c.restore(restore))
    await phase(c, "draining")
    assert not exported.is_set()
    with pytest.raises(MaintenanceBusy):
        async with c.operation("new-http"):
            pytest.fail("новый writer допущен")
    release.set()
    await task
    await resetting
    assert exported.is_set() and c.epoch == 1


@pytest.mark.parametrize("kind", ["audio", "seed"])
async def test_busy_protected_actor_refuses_before_effects_and_is_not_cancelled(kind):
    c = MaintenanceCoordinator()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def active():
        async with c.operation(kind):
            entered.set()
            await release.wait()

    actor = asyncio.create_task(active())
    await entered.wait()
    effects = []

    async def restore(job):
        effects.append(job)
        return job

    with pytest.raises(MaintenanceBusy):
        await c.restore(restore)
    assert not effects and c.phase == "ready" and not actor.cancelled()
    release.set()
    await actor


async def test_http_cancellation_does_not_release_gate_before_thread_and_headers():
    c = MaintenanceCoordinator()
    thread_started = threading.Event()
    release = threading.Event()
    headers = []

    def process():
        thread_started.set()
        assert release.wait(5)

    async def restore(job):
        await asyncio.to_thread(process)
        headers.append(job)
        return job

    caller = asyncio.create_task(c.restore(restore))
    await asyncio.wait_for(asyncio.to_thread(thread_started.wait, 2), 3)
    caller.cancel()
    assert c.phase == "restoring" and c._job is not None and not c._job.cancelled()
    with pytest.raises(MaintenanceBusy):
        async with c.operation("late-writer"):
            pytest.fail("gate открыт до завершения psql")
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert headers and c.phase == "ready" and c.epoch == 1


async def test_failed_closed_has_explicit_retry_and_no_permanent_deadlock():
    c = MaintenanceCoordinator()

    async def failed(_):
        raise RuntimeError("CSI failure")

    with pytest.raises(RuntimeError, match="CSI"):
        await c.restore(failed)
    assert c.phase == "failed"
    with pytest.raises(MaintenanceBusy):
        async with c.operation("ordinary"):
            pytest.fail("failed открыт")

    async def retry(job):
        return job

    async with c.operation("recovery-http", recovery=True):
        await c.restore(retry)
    assert c.phase == "ready"


async def test_preflight_failure_has_no_park_or_restore_effects():
    c = MaintenanceCoordinator()
    touched = []

    async def preflight():
        raise MaintenanceBusy("LLM config drift")

    async def park():
        touched.append("park")

    async def action(job):
        touched.append("restore")
        return job

    with pytest.raises(MaintenanceBusy):
        await c.restore(action, preflight=preflight, park=park)
    assert not touched and c.phase == "ready"


async def test_contextvar_inheritance_is_not_a_reentrant_child_lease():
    c = MaintenanceCoordinator()
    release = asyncio.Event()
    started = asyncio.Event()

    async def child():
        async with writer_lease("separate-child"):
            started.set()
            await release.wait()

    async with c.operation("http"):
        task = asyncio.create_task(child())
        await started.wait()
        assert len(c._records) == 2
        release.set()
        await task


async def test_reserved_child_rejects_stale_epoch_before_writer_body():
    c = MaintenanceCoordinator()
    touched = []

    async def stale():
        touched.append("stale ID")

    with c.bind():
        task = spawn_writer(stale(), kind="child")
    c.epoch += 1
    with pytest.raises(MaintenanceBusy):
        await task
    assert not touched


async def test_http_get_health_and_ws_audio_block_but_existing_metadata_is_db_free():
    c = MaintenanceCoordinator()
    c.phase = "restoring"
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    gate = MaintenanceMiddleware(app, coordinator=c)

    async def receive():
        return {"type": "http.request", "body": b""}

    messages = []

    async def send(message):
        messages.append(message)

    for path in ("/api/health", "/api/personal/session"):
        await gate({"type": "http", "path": path, "method": "GET"}, receive, send)
        assert messages[-2]["status"] == 503
    await gate({"type": "http", "path": "/api/sim/baseline", "method": "GET"}, receive, send)
    assert calls == ["/api/sim/baseline"]
    await gate({"type": "websocket", "path": "/ws/audio/1"}, receive, send)
    assert messages[-1] == {"type": "websocket.close", "code": 1013}


async def test_existing_readonly_stream_ws_keeps_progress_admission():
    c = MaintenanceCoordinator()
    c.phase = "restoring"
    called = []

    async def app(scope, receive, send):
        called.append(scope["path"])
        await send({"type": "websocket.accept"})

    messages = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages.append(message)

    await MaintenanceMiddleware(app, coordinator=c)({"type": "websocket", "path": "/ws/stream"}, receive, send)
    assert called == ["/ws/stream"] and messages == [{"type": "websocket.accept"}]
