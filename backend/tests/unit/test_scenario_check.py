"""Нереализованный сценарий не может давать зелёную приёмку (T-235)."""

from __future__ import annotations

import httpx
import pytest

from scripts import scenario_check


@pytest.mark.parametrize("number", [6, 12, 13])
async def test_not_implemented_scenario_is_a_failure(monkeypatch, capsys, number):
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(501, json={"detail": "not implemented"})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        scenario_check.httpx,
        "AsyncClient",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    result = await scenario_check.run_one(
        "http://test", "unused-no-database", {"id": "unsupported", "number": number, "title_ru": "Проверка"}, 0
    )
    assert result is False
    assert calls == [("POST", "/api/scenarios/unsupported/run")]
    assert "FAIL" in capsys.readouterr().out


async def test_all_scenarios_returns_failure_when_any_is_not_executed(monkeypatch):
    checked = []

    async def check(base, dsn, scenario, wait):
        checked.append(scenario["id"])
        return scenario["id"] != "unsupported"

    monkeypatch.setattr(scenario_check.sys, "argv", ["scenario_check.py", "all"])
    monkeypatch.setattr(scenario_check.sc, "load_all", lambda: [{"id": "unsupported"}, {"id": "supported"}])
    monkeypatch.setattr(scenario_check, "run_one", check)
    assert await scenario_check.main() == 1
    assert checked == ["unsupported", "supported"]
