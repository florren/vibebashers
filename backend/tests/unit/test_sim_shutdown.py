"""Ошибка flush не выдаётся за успешное завершение и не оставляет connection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.sim.engine import Simulator


@pytest.mark.asyncio
async def test_shutdown_reports_storage_failure_and_closes_connection(monkeypatch):
    sim = Simulator(seed=7)
    conn = SimpleNamespace(closed=False, commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock())
    sim.conn = conn
    monkeypatch.setattr(sim, "_require_current", AsyncMock())
    monkeypatch.setattr(sim, "persist", AsyncMock(side_effect=RuntimeError("own storage failure")))
    with pytest.raises(RuntimeError, match="own storage failure"):
        await sim.shutdown()
    conn.close.assert_awaited_once()
