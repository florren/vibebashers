from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agent import nodes
from app.agent.tools import router_tools
from app.agent.tools.base import ToolError
from tests.unit.test_router_tools import _ctx, _frame, _install_inners


async def test_product_route_single_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, _ = _ctx()
    ctx.act_frame = _frame()
    seen = {}
    _install_inners(monkeypatch, seen)
    original = ctx.fetchone

    async def fetch(sql, args=()):
        return ("team_deposits",) if "product_lines" in sql else await original(sql, args)

    monkeypatch.setattr(ctx, "fetchone", fetch)
    result = await router_tools.route_to_product_team(ctx, "deposits", 10)
    assert result["department"] == "team_deposits"
    assert seen["create"]["team"] == "team_deposits"
    assert len(ctx.calls) == 1
    assert ctx.calls[0]["name"] == "route_to_product_team"
    assert ctx.calls[0]["wraps"] == ["route_to_department"]
    assert ctx.calls[0]["side_effect"] is True
    assert nodes._router_matches("route", nodes._facade_names(ctx.calls))
    assert not nodes._router_matches("none", nodes._facade_names(ctx.calls))
    assert nodes._router_matches("escalate", ["route_to_product_team", "escalate_to_manager"])


async def test_wrong_signal_no_write(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, conn = _ctx()
    ctx.act_frame = _frame()
    with pytest.raises(ToolError, match="signal_id"):
        await router_tools.route_to_product_team(ctx, "deposits", 11)
    assert conn.sql == []


async def test_unknown_product_no_write(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, _ = _ctx()
    ctx.act_frame = _frame()
    monkeypatch.setattr(ctx, "fetchone", AsyncMock(return_value=None))
    with pytest.raises(ToolError, match="направление"):
        await router_tools.route_to_product_team(ctx, "unknown", 10)
