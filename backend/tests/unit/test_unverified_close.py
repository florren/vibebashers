"""Неподтверждённая услуга не закрывается и даёт допустимый контрактом outcome."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import nodes
from app.agent.nodes import close
from app.agent.state import new_state


async def test_unverified_close_fails_explicitly() -> None:
    state = {
        "signal": {"id": 1},
        "client": {},
        "decision": {},
        "actions": [{"incident_id": 2}],
        "verified": False,
        "errors": [],
    }
    deps = SimpleNamespace(record_step=AsyncMock())
    result = await close(state, deps)
    assert result["outcome"] == "failed"
    assert result["errors"] == ["close: услуга не подтверждена"]
    assert result["verified"] is False
    deps.record_step.assert_awaited_once()


@pytest.mark.parametrize(
    ("provider", "source"),
    [("gigachat", "live"), ("openai_compatible", "live"), ("replay", "replay"), ("mock", "mock")],
)
async def test_instant_decision_persists_contract_source(provider, source, monkeypatch) -> None:
    state = new_state(1, {"id": 3, "text": "Комиссия за QR", "channel": "chat"}, 2, "v1.1")
    conn = SimpleNamespace(execute=AsyncMock())
    deps = SimpleNamespace(ctx=SimpleNamespace(conn=conn), record_step=AsyncMock())
    monkeypatch.setattr(nodes, "_llm", AsyncMock(return_value=({}, {"provider": provider})))
    monkeypatch.setattr(nodes, "_postcheck_classification", lambda cls, state, deps: (cls, []))
    await nodes.instant_decide(state, deps)
    assert state["llm_source"] == source
    assert deps.ctx.llm_source == source
    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args[1]
    assert json.loads(args[0])["signal_type"] == "tariff_terms"
    assert json.loads(args[1])["incident_action"] == "create"
    assert args[2] == 3
