"""Решение оператора не ждёт обработки накопленного потока World/SLA."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from app.agent.runner import AgentService


async def test_hitl_resume_has_bounded_capacity_independent_of_inbound_queue(monkeypatch):
    service = AgentService(None, None, concurrency=1)
    conn = object()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    @asynccontextmanager
    async def connection():
        yield conn

    async def resume(connection, *, human_decision_id, **kwargs):
        assert connection is conn
        calls.append(human_decision_id)
        entered.set()
        await release.wait()
        return {"run_id": 7, "outcome": "deferred"}

    monkeypatch.setattr(service, "_conn", AsyncMock(side_effect=connection))
    monkeypatch.setattr("app.agent.runner.resume_after_human", resume)
    wake = AsyncMock()
    monkeypatch.setattr(service, "_wake_committed_graph", wake)
    tasks = []
    try:
        async with service.sem:
            tasks.append(asyncio.create_task(service.resume(1502)))
            await asyncio.wait_for(entered.wait(), timeout=1)
            tasks.append(asyncio.create_task(service.resume(1504)))
            await asyncio.sleep(0)
            assert calls == [1502], "Продолжения HITL ограничены одним активным графом"
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        assert calls == [1502, 1504]
        assert results == [{"run_id": 7, "outcome": "deferred"}] * 2
        assert wake.await_count == 2
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
