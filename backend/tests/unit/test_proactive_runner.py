"""Один service wakeup, без доверия к данным NOTIFY и без внешних вызовов."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.runner import AgentService
from app.sim.events import dumps

pytestmark = pytest.mark.asyncio


async def test_fault_wakeups_are_coalesced_without_payload_time_or_database(monkeypatch):
    service = AgentService(None, None)
    connect = AsyncMock(side_effect=AssertionError("NOTIFY не является фактом для SQL/графа"))
    monkeypatch.setattr(service, "_conn", connect)
    for event in ("fault.started", "op.failed") * 10:
        await service._notification(
            SimpleNamespace(
                channel="sim_events",
                payload=dumps({"event_type": event, "sim_time": "invalid", "payload": {"fault_id": -99}}),
            )
        )
    assert service._proactive_wake.is_set()
    assert not service._inflight
    connect.assert_not_awaited()
    service._proactive_wake.clear()
    service.enabled = False
    await service._notification(SimpleNamespace(channel="sim_events", payload=dumps({"event_type": "fault.started"})))
    assert not service._proactive_wake.is_set()


async def test_proactive_resume_and_regular_submit_share_inflight_slot(monkeypatch):
    service = AgentService(None, None)
    entered, release = asyncio.Event(), asyncio.Event()

    async def resume(signal_id):
        assert signal_id == 17
        entered.set()
        await release.wait()

    monkeypatch.setattr(service, "_resume_proactive", resume)
    process = AsyncMock()
    monkeypatch.setattr(service, "_process", process)
    task = service._submit_proactive_resume(17)
    await entered.wait()
    assert service._submit_proactive_resume(17) is task
    assert service.submit(17) is task
    release.set()
    await task
    await asyncio.sleep(0)
    assert not service._by_signal and not service._inflight
    process.assert_not_awaited()


async def test_proactive_daemon_wake_and_stop_preserve_cancellation(monkeypatch):
    service = AgentService(None, None)
    entered, second = asyncio.Event(), asyncio.Event()
    calls = 0

    async def cycle():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
        else:
            second.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(service, "_proactive_cycle", cycle)
    service._proactive_task = asyncio.create_task(service._proactive_loop())
    task = service._proactive_task
    await entered.wait()
    service._proactive_wake.set()
    await second.wait()
    await service.stop()
    assert task.cancelled() and service._proactive_task is None
    assert calls == 2
