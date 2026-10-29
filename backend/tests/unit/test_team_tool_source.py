"""Эмулятор команды пишет допустимый контрактом источник вызова инструмента."""

import pytest

from app.agent.tools.base import ToolContext
from app.contracts.registry import validate
from app.sim.clock import add_working_days
from app.sim.rng import SimRng
from tests.unit.test_teams import MemStore, _emu, _run_until_closed


async def test_team_status_tool_sources_follow_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    iid = store.add_incident()
    sources = []

    async def track(ctx: ToolContext, incident_id: int, status: str, reason=None, fields=None):
        call = {
            "name": "update_incident",
            "args": {"incident_id": incident_id, "status": status},
            "source": ctx.llm_source,
            "ok": True,
            "side_effect": True,
            "ms": 0,
            "result": {"incident_id": incident_id, "status": status},
        }
        assert validate(call, "agent/tool_call") == []
        sources.append(ctx.llm_source)
        store.incidents[incident_id]["status"] = status
        return call["result"]

    monkeypatch.setattr("app.sim.teams.update_incident", track)
    monkeypatch.setattr(SimRng, "random", lambda self: 0.5)
    emulator, _, _ = _emu(store)
    await _run_until_closed(emulator, store, add_working_days(store.incidents[iid]["created_sim"], 12))
    assert len(sources) == 6
    assert store.incidents[iid]["status"] == "closed"
