"""Восстановление полного состояния записи, в том числе пустой истории."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.graph import _restore_recording_state


@pytest.mark.parametrize("row", [(30, 12, 250, Decimal("0.25"), 3, 1024), (0, 0, 0, None, 0, 0)])
async def test_restore_recording_state(row):
    conn = AsyncMock()
    conn.execute.return_value.fetchone.return_value = row
    deps = SimpleNamespace(ctx=SimpleNamespace(agent_run_id=9), tokens={}, steps=[], text_bytes_used=0)
    await _restore_recording_state(conn, deps)
    assert deps.tokens == {"prompt": row[0], "completion": row[1], "latency_ms": row[2], "cost": float(row[3] or 0)}
    assert len(deps.steps) == row[4]
    assert deps.text_bytes_used == row[5]


async def test_missing_run_does_not_silently_reset_usage():
    conn = AsyncMock()
    conn.execute.return_value.fetchone.return_value = None
    with pytest.raises(RuntimeError, match="Запуск агента отсутствует"):
        await _restore_recording_state(conn, SimpleNamespace(ctx=SimpleNamespace(agent_run_id=9)))
