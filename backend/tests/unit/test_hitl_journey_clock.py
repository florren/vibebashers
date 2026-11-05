"""Выбор времени HITL не заимствует часы другого запуска для Journey."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.api import hitl
from app.demo import journey

AT = dt.datetime(2026, 11, 10, 9, tzinfo=dt.UTC)


async def test_journey_uses_own_facts_and_requested_floor(monkeypatch):
    fetch = AsyncMock(return_value={"created_by": "journey_demo", "started_sim": AT})
    own_clock = AsyncMock(return_value=AT + dt.timedelta(hours=3))
    monkeypatch.setattr(hitl, "fetch_one", fetch)
    monkeypatch.setattr(journey, "clock", own_clock)
    conn = object()
    assert await hitl._hitl_sim_time(conn, 17, event_floor=AT + dt.timedelta(hours=2)) == AT + dt.timedelta(hours=3)
    own_clock.assert_awaited_once_with(conn, 17, AT + dt.timedelta(hours=2))
    assert fetch.await_count == 1


async def test_explicit_demo_override_keeps_precedence_without_reading_global_clock(monkeypatch):
    fetch = AsyncMock(side_effect=AssertionError("override must not read another clock"))
    monkeypatch.setattr(hitl, "fetch_one", fetch)
    at = AT + dt.timedelta(hours=2)
    assert await hitl._hitl_sim_time(object(), 17, override=at) == at
    fetch.assert_not_awaited()


@pytest.mark.parametrize("creator", [None, "public_demo", "scenario", "simulation"])
async def test_other_modes_preserve_global_clock(monkeypatch, creator):
    fetch = AsyncMock(side_effect=[{"created_by": creator, "started_sim": AT}, {"sim_time": AT + dt.timedelta(days=3)}])
    own_clock = AsyncMock(side_effect=AssertionError("not a Journey case"))
    monkeypatch.setattr(hitl, "fetch_one", fetch)
    monkeypatch.setattr(journey, "clock", own_clock)
    assert await hitl._hitl_sim_time(object(), 17, event_floor=AT) == AT + dt.timedelta(days=3)
    own_clock.assert_not_awaited()
