"""Нереализованный сценарий не может давать зелёную приёмку (T-235)."""

from __future__ import annotations

import json

import httpx
import pytest
from scripts import scenario_check


@pytest.mark.parametrize(
    ("scenario_id", "expected_body", "allow_baseline_reset"),
    [
        ("deposit_promo_rate", {"reset_mode": "baseline"}, True),
        ("potential_client", {"reset_mode": "baseline"}, True),
        ("silent_churn_regression", {"reset_mode": "baseline"}, True),
        ("double_fee", {}, True),
        ("double_fee", {}, False),
    ],
)
async def test_scenario_run_respects_catalog_required_reset_mode(
    monkeypatch, scenario_id, expected_body, allow_baseline_reset
):
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path, json.loads(request.content)))
        # Проверяем только исходящий запрос: 501 завершает путь до обращения к БД.
        return httpx.Response(501, json={"detail": "not implemented"})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        scenario_check.httpx,
        "AsyncClient",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    scenario = scenario_check.sc.get(scenario_id)
    assert scenario is not None
    assert (
        await scenario_check.run_one(
            "http://test", "unused-no-database", scenario, 0, allow_baseline_reset=allow_baseline_reset
        )
        is False
    )
    assert calls == [("POST", f"/api/scenarios/{scenario_id}/run", expected_body)]


@pytest.mark.parametrize("scenario_id", ["deposit_promo_rate", "potential_client", "silent_churn_regression"])
async def test_required_baseline_without_operator_opt_in_sends_no_request(monkeypatch, capsys, scenario_id):
    def forbidden_client(**kwargs):
        raise AssertionError("baseline без opt-in не должен создавать HTTP client")

    monkeypatch.setattr(scenario_check.httpx, "AsyncClient", forbidden_client)
    scenario = scenario_check.sc.get(scenario_id)
    assert scenario is not None
    assert await scenario_check.run_one("http://test", "unused-no-database", scenario, 0) is False
    assert "--allow-baseline-reset" in capsys.readouterr().out


@pytest.mark.parametrize("outcome", ["failed", "error", "completed", "deferred"])
async def test_failed_native_graph_cannot_pass_empty_scenario_expectations(monkeypatch, outcome):
    async def recorded_data(conn, run_id):
        return {
            "signals": [{"classification": {}, "decision": {}}],
            "incidents": [],
            "agent_runs": [{"outcome": outcome}],
        }

    monkeypatch.setattr(scenario_check.sc, "_run_data", recorded_data)
    result = await scenario_check.sc.evaluate(None, {"id": "recorded", "expected": {}}, 1)
    failed = outcome in ("failed", "error")
    assert result["counts"]["errors"] == int(failed)
    assert result["passed"] is not failed


@pytest.mark.parametrize("kind", ["runs", "transcript"])
@pytest.mark.parametrize("terminal", [False, True])
async def test_processing_wait_reports_completion_or_timeout(monkeypatch, kind, terminal):
    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, *args):
            return self

        async def fetchone(self):
            return (1,)

    async def connect(dsn):
        return Connection()

    monkeypatch.setattr(scenario_check.psycopg.AsyncConnection, "connect", connect)
    timeout = 60 if terminal else 0
    if kind == "runs":
        result = await scenario_check._wait_runs("unused-no-database", 1, 1, timeout)
    else:
        result = await scenario_check._wait_transcript("unused-no-database", 1, timeout)
    assert result is terminal


@pytest.mark.parametrize("kind", ["runs", "transcript"])
async def test_processing_timeout_cannot_pass_recorded_scenario(monkeypatch, kind):
    saved = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def commit(self):
            pass

    async def connect(dsn):
        return Connection()

    async def timed_out(*args):
        return False

    async def evaluate(*args):
        return {"passed": True, "checks": [], "counts": {"signals": 1}}

    async def save(conn, scenario_id, result):
        saved.append(result)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        scenario_check.httpx,
        "AsyncClient",
        lambda **kwargs: client(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(202, json={"run": {"id": 77}}))
        ),
    )
    monkeypatch.setattr(scenario_check.psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(scenario_check.sc, "is_transcript", lambda scenario: kind == "transcript")
    monkeypatch.setattr(scenario_check, "_wait_runs" if kind == "runs" else "_wait_transcript", timed_out)
    monkeypatch.setattr(scenario_check.sc, "evaluate", evaluate)
    monkeypatch.setattr(scenario_check.sc, "save_result", save)
    assert (
        await scenario_check.run_one(
            "http://test",
            "unused-no-database",
            {"id": "pending", "number": 1, "title_ru": "Проверка", "inject": [{}]},
            0,
        )
        is False
    )
    assert saved and saved[0]["passed"] is False
    assert any(check["ok"] is False and check["code"] == "processing_completed" for check in saved[0]["checks"])


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


async def test_all_forwards_explicit_baseline_permission(monkeypatch):
    checked = []

    async def check(base, dsn, scenario, wait, *, allow_baseline_reset=False):
        checked.append((scenario["id"], allow_baseline_reset))
        return True

    monkeypatch.setattr(scenario_check.sys, "argv", ["scenario_check.py", "all", "--allow-baseline-reset"])
    monkeypatch.setattr(scenario_check.sc, "load_all", lambda: [{"id": "required"}, {"id": "ordinary"}])
    monkeypatch.setattr(scenario_check, "run_one", check)
    assert await scenario_check.main() == 0
    assert checked == [("required", True), ("ordinary", True)]


async def test_journey_alias_selects_readonly_scenario_with_explicit_live_recording(monkeypatch):
    checked = []

    async def check(base, dsn, scenario, wait):
        checked.append((scenario["id"], scenario["_recording_source"]))
        return True

    monkeypatch.setattr(
        scenario_check.sys, "argv", ["scenario_check.py", "journey_three_trajectories", "--recording-source", "live"]
    )
    monkeypatch.setattr(
        scenario_check.sc,
        "load_all",
        lambda: [{"id": "customer_journey", "number": 12, "aliases": ["journey_three_trajectories"]}, {"id": "other"}],
    )
    monkeypatch.setattr(scenario_check, "run_one", check)
    assert await scenario_check.main() == 0
    assert checked == [("customer_journey", "live")]
