"""HTTP ingest стартует агента после commit и не дублирует LISTEN-задачу."""

from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.agent.runner import AgentService
from app.api import ingest


async def test_ingest_dispatches_only_accepted_after_commit(monkeypatch):
    committed = False

    @asynccontextmanager
    async def db():
        nonlocal committed
        yield object()
        committed = True

    stamp = dt.datetime(2026, 11, 9, tzinfo=dt.UTC)
    create = AsyncMock(return_value={"status": "accepted", "signal_id": 17})
    context = AsyncMock(return_value=(7, stamp))

    def submit(signal_id):
        assert committed
        assert signal_id == 17

    agent = SimpleNamespace(enabled=True, submit=Mock(side_effect=submit))
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(agent=agent)))
    monkeypatch.setattr(ingest, "db", db)
    monkeypatch.setattr(ingest, "create_signal", create)
    monkeypatch.setattr(ingest, "run_context", context)
    result = await ingest.post_ingest_messages(request, {"text": "Синтетическое обращение"})
    assert result.status_code == 202
    agent.submit.assert_called_once_with(17)
    context.assert_awaited_once()
    assert create.call_args.kwargs["run_id"] == 7
    assert create.call_args.kwargs["sim_time"] == stamp


async def test_agent_submit_coalesces_concurrent_http_and_listen(monkeypatch):
    service = AgentService(object(), object())
    release = asyncio.Event()
    calls = []

    async def process(signal_id, _sim_time):
        calls.append(signal_id)
        await release.wait()

    monkeypatch.setattr(service, "_process", process)
    first = service.submit(17)
    assert service.submit(17) is first
    await asyncio.sleep(0)
    assert calls == [17]
    release.set()
    await first
    await asyncio.sleep(0)
    assert not service._by_signal
    assert not service._inflight


async def test_personal_slot_uses_same_graph_without_waiting_for_bulk_semaphore(monkeypatch):
    from unittest.mock import AsyncMock

    from app.agent import runner

    service = AgentService(object(), object(), concurrency=1)
    service.sem = asyncio.Semaphore(0)

    @asynccontextmanager
    async def connection():
        yield object()

    async def connect():
        return connection()

    graph = AsyncMock(return_value={"outcome": "completed"})
    monkeypatch.setattr(service, "_conn", connect)
    monkeypatch.setattr(runner, "process_signal", graph)
    await asyncio.wait_for(service._process(17, None, interactive=True), timeout=1)
    graph.assert_awaited_once()
    assert graph.call_args.kwargs["signal_id"] == 17 and service.processed == 1
