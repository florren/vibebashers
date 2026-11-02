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
    for event in ("fault.started", "op.failed", "scenario.proactive_notified", "scenario.proactive_completed") * 10:
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


@pytest.mark.parametrize("owned", [True, False])
async def test_graph_progress_wakes_only_after_commit_and_native_owned_scope(monkeypatch, owned):
    import datetime as dt

    from app.agent import proactive

    service = AgentService(None, None, sim=SimpleNamespace(run_id=7))
    committed = []

    async def commit():
        assert not service._proactive_wake.is_set()
        committed.append(True)

    conn = SimpleNamespace(commit=commit)
    clock = AsyncMock(return_value=(7, dt.datetime.now(dt.UTC)) if owned else None)
    monkeypatch.setattr(proactive, "current_clock", clock)
    await service._wake_committed_graph(conn, {"run_id": 7})
    assert committed == [True]
    assert service._proactive_wake.is_set() is owned
    clock.assert_awaited_once_with(conn, 7)


async def test_noop_graph_completion_and_standalone_caller_never_self_wake_or_read_foreign_scope(monkeypatch):
    from app.agent import proactive

    scope = AsyncMock(side_effect=AssertionError("No-op не читает/меняет foreign scope"))
    monkeypatch.setattr(proactive, "current_clock", scope)
    conn = SimpleNamespace(commit=AsyncMock(side_effect=AssertionError("No-op не commit")))
    service = AgentService(None, None, sim=SimpleNamespace(run_id=7))
    await service._wake_committed_graph(conn, None)
    assert not service._proactive_wake.is_set()
    standalone = AgentService(None, None)
    await standalone._wake_committed_graph(conn, {"run_id": 999})
    assert not standalone._proactive_wake.is_set()
    scope.assert_not_awaited()
    conn.commit.assert_not_awaited()


@pytest.mark.parametrize("progress", [False, True])
async def test_phase_clock_wake_is_only_committed_progress_not_noop_tick(monkeypatch, progress):
    import datetime as dt

    from app.agent import proactive
    from app.sim import proactive_phases

    at = dt.datetime.now(dt.UTC)
    sim = SimpleNamespace(run_id=7, clock=SimpleNamespace(sim_time=at))
    service = AgentService(None, None, sim=sim)

    class Connection:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self):
            if self.calls == 0:
                assert not service._proactive_wake.is_set()
            self.calls += 1

        async def execute(self, sql, args):
            assert sql.startswith("select s.id,a.id,a.outcome,s.origin")
            assert args == ([],)
            return SimpleNamespace(fetchall=AsyncMock(return_value=[]))

    conn = Connection()
    monkeypatch.setattr(service, "_conn", AsyncMock(return_value=conn))
    monkeypatch.setattr(proactive, "produce", AsyncMock(return_value=[]))

    async def advance(actual, owner):
        assert actual is conn and owner is sim
        if progress:
            sim.clock.sim_time = at + dt.timedelta(minutes=1)
        return []

    monkeypatch.setattr(proactive_phases, "advance", advance)
    submit = AsyncMock(side_effect=AssertionError("No-op/clock hint не создаёт foreign graph"))
    monkeypatch.setattr(service, "submit", submit)
    await service._proactive_cycle()
    assert service._proactive_wake.is_set() is progress
    assert not service._inflight
    submit.assert_not_called()
