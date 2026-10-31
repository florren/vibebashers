"""Регрессии пяти demo-траекторий и честного источника LLM."""

import datetime as dt

import pytest

from app.api.demo_execution import DemoExecutionBody
from app.demo.roles import respond
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.sim.clock import MSK, add_working_days, add_working_hours
from app.sim.teams import _plan_blob, _plan_from_blob, demo_plan


@pytest.mark.parametrize("outcome", ["on_time", "late", "no_work", "failed", "recovered"])
def test_demo_outcome_evidence_and_deadlines(outcome: str) -> None:
    created = dt.datetime(2026, 11, 9, 9, tzinfo=MSK)
    take = add_working_hours(created, 4)
    due = add_working_days(created, 2)
    plan = demo_plan(10, "team_deposits", outcome, created, take, due)
    actions = [s.action for s in plan.steps]
    assert [s.at for s in plan.steps] == sorted(s.at for s in plan.steps)
    if outcome in ("no_work", "failed"):
        assert "close" not in actions
        assert "release" not in actions
        assert "verify" not in actions
        assert "escalate_ack" in actions
        if outcome == "no_work":
            assert actions == ["escalate_ack"]
        else:
            assert "rca" in actions and "progress_report" in actions
    else:
        assert actions.index("release") < actions.index("verify") < actions.index("close")
        if outcome == "recovered":
            assert actions.index("escalate_ack") < actions.index("release")
        closed = next(s.at for s in plan.steps if s.action == "close")
        assert (closed <= due) == (outcome == "on_time")
    assert _plan_blob(_plan_from_blob(10, _plan_blob(plan))) == _plan_blob(plan)
    assert demo_plan(10, "team_deposits", outcome, created, take, due) == plan


def test_unknown_demo_outcome_rejected() -> None:
    with pytest.raises(ValueError):
        DemoExecutionBody(scenario_id="x", team_outcome="pretend_success")


@pytest.mark.asyncio
async def test_offline_role_is_honestly_marked_mock() -> None:
    body = "Проблема не решена, требуется дополнительная работа команды."
    obj, meta = await respond(
        ProviderChain([MockProvider(latency_ms=0)]),
        LLMProfile(code="mock", provider="mock", model="mock"),
        {"role": "product_team", "outcome": "failed", "language": "ru"},
        body,
    )
    assert obj["body"] == body
    assert meta["source"] == "mock"
    assert meta["demo"] is True
    assert meta["usage"]["total_tokens"] > 0


def test_twenty_input_cases_are_runnable_and_grounded() -> None:
    from app.sim.scenarios import is_runnable, load_all

    scenarios = [s for s in load_all() if s["id"].startswith("demo20_")]
    assert len(scenarios) == 20
    assert len({s["id"] for s in scenarios}) == 20
    for scenario in scenarios:
        assert is_runnable(scenario)
        assert scenario["demo_evidence"]["source"] == "synthetic_fixture"
        assert all(scenario["demo_evidence"][k] for k in ("observed", "action", "verification"))


def test_demo_employee_projection_is_distinct_from_human() -> None:
    from app.trace.projections import project

    node = {
        "kind": "human_decision",
        "id": 1,
        "scope_id": 2,
        "data": {
            "id": 1,
            "public_id": "HD-000001",
            "decision": "accept",
            "decided_by": "demo-agent:operator:mock",
            "requested_at": "2026-10-31T00:00:00Z",
        },
    }
    result = project(node, "after")
    assert "DEMO" in result["title_ru"]
    assert "эмуляция" in result["actor"]["label_ru"]
    assert result["badges"]["llm_source"] == "mock"


def test_on_time_hard_case_meets_every_progress_report_deadline() -> None:
    created = dt.datetime(2026, 11, 9, 9, tzinfo=MSK)
    reports = [add_working_days(created, day) for day in (3, 6, 9)]
    plan = demo_plan(
        10, "team_deposits", "on_time", created, add_working_hours(created, 4), add_working_days(created, 10), reports
    )
    actual = [s for s in plan.steps if s.action == "progress_report"]
    assert [s.due for s in actual] == reports
    assert all(created <= s.at < s.due for s in actual)
    assert _plan_blob(_plan_from_blob(10, _plan_blob(plan))) == _plan_blob(plan)


def test_reverse_working_interval_skips_weekend_and_is_not_negative_add() -> None:
    from app.sim.teams import _before_working_hours

    monday = dt.datetime(2026, 11, 9, 9, tzinfo=MSK)
    assert _before_working_hours(monday, 0.25) == dt.datetime(2026, 11, 6, 17, 45, tzinfo=MSK)
    assert _before_working_hours(monday, 0) == monday
    with pytest.raises(ValueError):
        _before_working_hours(monday, -1)
