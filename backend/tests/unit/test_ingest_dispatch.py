"""HTTP ingest стартует агента после commit и не дублирует LISTEN-задачу."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from app.agent.runner import AgentService
from app.api import ingest


async def test_ingest_dispatches_only_accepted_after_commit(monkeypatch):
    committed = False

    @asynccontextmanager
    async def db():
        nonlocal committed
        yield object()
        committed = True

    async def create(*_args, **_kwargs):
        return {"status": "accepted", "signal_id": 17}

    def submit(signal_id):
        assert committed
        assert signal_id == 17

    agent = SimpleNamespace(enabled=True, submit=Mock(side_effect=submit))
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(agent=agent)))
    monkeypatch.setattr(ingest, "db", db)
    monkeypatch.setattr(ingest, "create_signal", create)
    result = await ingest.post_ingest_messages(request, {"text": "Синтетическое обращение"})
    assert result.status_code == 202
    agent.submit.assert_called_once_with(17)


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
