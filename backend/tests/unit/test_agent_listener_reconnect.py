"""LISTEN предшествует durable catch-up; reconnect не повторяет эффекты графа."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest

from app.agent.runner import AgentService

pytestmark = pytest.mark.asyncio


async def test_listen_before_recovery_and_catchup_retries_only_network_failure(monkeypatch):
    service = AgentService(None, None)
    order = []
    recovered = asyncio.Event()
    iterations = 0

    class Conn:
        async def execute(self, sql):
            assert sql == "LISTEN sim_events"
            order.append("listen")

        async def close(self):
            order.append("close")

        async def notifies(self, **kwargs):
            assert kwargs == {"timeout": 2, "stop_after": 20}
            await asyncio.Event().wait()
            yield None

    connect = AsyncMock(side_effect=[Conn(), Conn()])
    monkeypatch.setattr("app.agent.runner.psycopg.AsyncConnection.connect", connect)

    async def recovery():
        nonlocal iterations
        iterations += 1
        order.append("recover")
        if iterations == 1:
            raise psycopg.OperationalError("synthetic disconnected startup")

    async def catchup():
        order.append("catchup")
        recovered.set()

    monkeypatch.setattr(service, "_recover", recovery)
    monkeypatch.setattr(service, "_catch_up_new", catchup)
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        assert seconds in (0, 1.0)
        await real_sleep(0)

    monkeypatch.setattr("app.agent.runner.asyncio.sleep", sleep)
    task = asyncio.create_task(service._loop())
    await asyncio.wait_for(recovered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert order == ["listen", "recover", "close", "listen", "recover", "catchup", "close"]


async def test_listener_disconnect_catches_up_after_reattach_without_replaying_startup(monkeypatch):
    service = AgentService(None, None)
    service._recover_on_start = False
    received = asyncio.Event()
    order = []

    class Conn:
        def __init__(self, fails):
            self.fails = fails

        async def execute(self, sql):
            order.append("listen")

        async def close(self):
            order.append("close")

        async def notifies(self, **kwargs):
            if self.fails:
                raise psycopg.OperationalError("synthetic disconnect; notification lost")
            received.set()
            await asyncio.Event().wait()
            yield None

    monkeypatch.setattr(
        "app.agent.runner.psycopg.AsyncConnection.connect", AsyncMock(side_effect=[Conn(True), Conn(False)])
    )
    catchup = AsyncMock(side_effect=lambda: order.append("catchup"))
    monkeypatch.setattr(service, "_catch_up_new", catchup)
    recovery = AsyncMock()
    monkeypatch.setattr(service, "_recover", recovery)
    real_sleep = asyncio.sleep
    monkeypatch.setattr("app.agent.runner.asyncio.sleep", lambda _: real_sleep(0))
    task = asyncio.create_task(service._loop())
    await asyncio.wait_for(received.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert order == ["listen", "catchup", "close", "listen", "catchup", "close"]
    recovery.assert_not_awaited()


@pytest.mark.parametrize("state", ["manual_pause", "disabled", "no_sim", "foreign_run"])
async def test_catchup_does_not_connect_when_local_owner_disallows(monkeypatch, state):
    service = AgentService(None, None, sim=SimpleNamespace(run_id=7, clock=SimpleNamespace(running=True)))
    if state == "manual_pause":
        service.sim.clock.running = False
    elif state == "disabled":
        service.enabled = False
    elif state == "no_sim":
        service.sim = None
    else:
        assert not service._catchup_allowed(8)
        return
    connection = AsyncMock(side_effect=AssertionError("no database work after manual pause"))
    monkeypatch.setattr(service, "_conn", connection)
    await service._catch_up_new()
    connection.assert_not_awaited()
