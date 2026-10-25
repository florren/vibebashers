"""T-078: выбор подарка и автовыдача после resolved."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import gifts
from app.agent.tools.base import ToolContext


def test_vip_medium_lounge_requires_hitl() -> None:
    g = gifts.choose("vip", "medium", [], None)
    assert g is not None
    assert g["points"] == 600
    assert g["privilege_code"] == "lounge_pass"
    assert g["requires_hitl"] is True
    assert g["when"] == "after_resolved"


def test_mass_points_no_hitl_auto_after_resolved() -> None:
    g = gifts.choose("mass", "high", ["repeat"], None)
    assert g is not None
    assert g["points"] == 1000
    assert g["privilege_code"] is None
    assert g["requires_hitl"] is False
    assert gifts.should_auto_issue(requires_hitl=False, when="after_resolved", incident_status="in_progress") is False
    assert gifts.should_auto_issue(requires_hitl=False, when="after_resolved", incident_status="resolved") is True


def test_bonus_hunter_cap() -> None:
    g = gifts.choose("mass", "low", [], "bonus_hunter")
    assert g is not None and g["points"] == 1000


def test_status_oriented_vip_low_lounge() -> None:
    g = gifts.choose("vip", "low", [], "status_oriented")
    assert g is not None
    assert g["privilege_code"] == "lounge_pass"
    assert g["requires_hitl"] is True


def test_ultra_vip_points_only_requires_hitl() -> None:
    g = gifts.choose("ultra_vip", "high", ["churn_intent"], None)
    assert g is not None
    assert g["points"] == 1000
    assert g["privilege_code"] is None
    assert g["requires_hitl"] is True


def test_should_auto_issue_false_lounge_and_mass_before_resolved() -> None:
    g = gifts.choose("vip", "medium", [], None)
    assert g is not None
    assert (
        gifts.should_auto_issue(requires_hitl=bool(g["requires_hitl"]), when=g["when"], incident_status="resolved")
        is False
    )
    mass = gifts.choose("mass", "medium", [], None)
    assert mass is not None
    assert (
        gifts.should_auto_issue(
            requires_hitl=bool(mass["requires_hitl"]), when=mass["when"], incident_status="in_progress"
        )
        is False
    )


@pytest.mark.asyncio
async def test_issue_automatic_idempotent_done() -> None:
    payload = {"gift": {"gift_code": "bonus_points", "points": 300}, "when": "after_resolved", "issued": True}
    conn = MagicMock()
    conn.execute = AsyncMock(
        return_value=MagicMock(
            fetchall=AsyncMock(
                return_value=[
                    (
                        1,
                        10,
                        payload,
                        False,
                        5,
                        99,
                        "mass",
                        "Клиент",
                        "resolved",
                        None,
                        None,
                    )
                ]
            ),
            description=[
                type("C", (), {"name": n})()
                for n in (
                    "task_id",
                    "run_id",
                    "payload",
                    "requires_hitl",
                    "client_id",
                    "incident_id",
                    "client_segment",
                    "client_name",
                    "incident_status",
                    "gift_name",
                    "sim_time",
                )
            ],
        )
    )
    ctx = ToolContext(conn, run_id=10, agent_run_id=1, sim_time=dt.datetime.now(dt.UTC))
    n = await gifts.issue_automatic(ctx, 99)
    assert n == 0
    conn.execute.assert_called_once()
