"""T-067: границы ручного ввода и невозможность записи из сравнения."""

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent import comparison
from app.agent.tools.base import ToolContext, ToolError, tool
from app.api.engine import CompareBody
from app.api.signals import SignalCreate
from app.main import create_app


def test_jury_limit_sliding_window_and_retry_after():
    limiter = comparison.JuryRateLimit()
    for _ in range(20):
        limiter.check(0)
    with pytest.raises(HTTPException) as error:
        limiter.check(0.5)
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "60"}
    limiter.check(60)
    assert list(limiter.hits) == [60]


@pytest.mark.parametrize("body_type", [CompareBody, SignalCreate])
@pytest.mark.parametrize("size", [3, 4001, 5000])
def test_manual_input_accepts_approved_boundaries(body_type, size):
    body = body_type(text="а" * size, channel_code="chat")
    assert len(body.text) == size


@pytest.mark.parametrize("body_type", [CompareBody, SignalCreate])
@pytest.mark.parametrize("size", [2, 5001])
def test_manual_input_rejects_outside_approved_boundaries(body_type, size):
    with pytest.raises(ValidationError):
        body_type(text="а" * size, channel_code="chat")


@pytest.mark.parametrize("path", ["/api/signals", "/api/agent/compare"])
@pytest.mark.parametrize("text", ["а", "а" * 5001])
def test_text_limit_before_processing(path, text):
    with TestClient(create_app()) as client:
        response = client.post(path, json={"text": text, "channel_code": "chat"})
    assert response.status_code == 422


def test_both_endpoints_share_jury_budget(monkeypatch):
    async def fake(*args):
        return ({"signal_type": "info_request"}, 1), ({"signal_type": "churn"}, 2)

    monkeypatch.setattr("app.api.engine.compare_classifications", fake)
    with TestClient(create_app()) as client:
        for _ in range(20):
            response = client.post("/api/agent/compare", json={"text": "Сколько стоит карта?", "channel_code": "chat"})
            assert response.status_code == 200
            assert response.json()["llm_run_id"] == 1
            assert response.json()["mock_run_id"] == 2
        response = client.post("/api/signals", json={"text": "Не работает карта", "channel_code": "chat"})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_standalone_models_run_concurrently(monkeypatch):
    entered = []
    ready = asyncio.Event()

    async def classify(text, channel, cid, profile, chain):
        entered.append(profile.code)
        if len(entered) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 0.5)
        return {"model": profile.code}, len(entered)

    monkeypatch.setattr(comparison, "_classification", classify)
    result = await comparison.compare_classifications("тест", "chat", None, SimpleNamespace(code="main"), object())
    assert entered == ["main", "compare_mock"]
    assert result[0][0] == {"model": "main"}


async def test_dry_run_blocks_write_tool_before_call():
    invoked = False

    @tool("create_incident")
    async def forbidden(ctx):
        nonlocal invoked
        invoked = True
        await ctx.conn.execute("update signals set status='error'")

    conn = SimpleNamespace(execute=AsyncMock())
    ctx = ToolContext(conn, run_id=1, agent_run_id=2, sim_time=dt.datetime.now(dt.UTC), dry_run=True)
    with pytest.raises(ToolError, match="недоступен в сравнении"):
        await forbidden(ctx)
    assert not invoked
    conn.execute.assert_not_awaited()
    assert ctx.calls[0]["ok"] is False


async def test_dry_run_only_publishes_trace_events_on_audit_connection():
    reader = SimpleNamespace(execute=AsyncMock())
    writer = SimpleNamespace(execute=AsyncMock())
    ctx = ToolContext(
        reader, run_id=1, agent_run_id=2, sim_time=dt.datetime.now(dt.UTC), dry_run=True, trace_conn=writer
    )
    await ctx.notify("signals", "classified", {"id": 3})
    await ctx.notify("notifications", "sent", {})
    await ctx.notify("agent", "step_finished", {})
    reader.execute.assert_not_awaited()
    assert writer.execute.await_count == 1
    assert writer.execute.call_args.args[1][0] == "agent"


async def test_standalone_failure_waits_for_other_audit(monkeypatch):
    completed = asyncio.Event()

    async def classify(text, channel, cid, profile, chain):
        if profile.code == "main":
            raise ValueError("invalid model result")
        await asyncio.sleep(0)
        completed.set()
        return {}, 2

    monkeypatch.setattr(comparison, "_classification", classify)
    with pytest.raises(ValueError, match="invalid model result"):
        await comparison.compare_classifications("тест", "chat", None, SimpleNamespace(code="main"), object())
    assert completed.is_set()


async def test_cancelled_comparison_finishes_audit(monkeypatch):
    async def cancel(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(comparison.nodes, "normalize", cancel)
    finish = AsyncMock()
    monkeypatch.setattr(comparison, "_finish", finish)
    deps = SimpleNamespace(ctx=SimpleNamespace(agent_run_id=1), begin_step=AsyncMock())
    run = comparison.MockComparison({}, deps, object())
    with pytest.raises(asyncio.CancelledError):
        await run.run()
    assert finish.await_args.kwargs == {"cancelled": True}
