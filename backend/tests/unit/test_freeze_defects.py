"""Регрессии дефектов, воспроизведённых при приёмке стенда."""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import nodes
from app.api.envfile import read_env_file, write_env_file
from app.config import Settings
from app.contracts.registry import validate
from app.llm.mock import analyze
from app.sim.clock import MSK, add_working_hours
from app.sim.teams import _plan_blob
from app.trace.journey import client_messages
from tests.unit.test_teams import MemStore, _emu, _World


@pytest.mark.parametrize("system,product", [(None, "deposit"), ("sub_deposits", None)])
async def test_missing_origin_cannot_plan_a_cross_system_regression(system, product):
    store = MemStore()
    store.teams["team_deposits"]["p_regression"] = 1.0
    store.add_incident(system_code=system, product_code=product)
    emu, _, _ = _emu(store)
    await emu.tick(dt.datetime(2026, 11, 9, 8, tzinfo=MSK), _World())
    plan = _plan_blob(emu.plans[1])
    assert all(step.get("regression") is None for step in plan["steps"])
    assert (
        validate(
            {"event_type": "team.plan", "version": 1, "incident_id": 1, "team": "team_deposits", "plan": plan},
            "sim/team_plan",
        )
        == []
    )


@pytest.mark.parametrize("clarify", [False, True])
def test_short_sla_never_places_verification_before_release(clarify):
    store = MemStore()
    emu, _, _ = _emu(store)
    start = dt.datetime(2026, 11, 9, 9, tzinfo=MSK)
    due = add_working_hours(start, 2)
    profile = {"take_hours": [1, 1], "p_clarify": int(clarify), "p_sla_breach": 0, "p_regression": 0}
    plan = emu._build_plan(
        1, "team_deposits", profile, start, add_working_hours(start, 1), due, [], "sub_deposits", "deposit"
    )
    at = {step.action: step.at for step in plan.steps}
    assert at["take"] <= at["rca"] <= at["fix_decision"] <= at["release"] <= at["verify"] < at["close"]
    assert at["close"] > due and plan.sla_breach


def test_gratitude_does_not_swallow_a_followup_question():
    result = analyze("Спасибо. Как проверить статус обращения?")
    assert result["signal_type"] == "info_request"
    assert "question" in result["intents"]
    assert analyze("Спасибо за помощь, вопросов больше нет.")["signal_type"] == "gratitude"


def test_anonymous_journey_includes_only_verified_conversation_members():
    subject = {"kind": "signal", "data": {"id": 1, "client_id": None}}
    nodes = [subject]
    for sid in [1, 2, 3]:
        nodes.append(
            {
                "kind": "notification",
                "data": {
                    "signal_id": sid,
                    "client_id": None,
                    "recipient_type": "client",
                    "status": "sent",
                    "sent_at": "2026-11-04T09:00:00Z",
                    "channel_code": "landing",
                    "body": f"Ответ{sid}",
                },
            }
        )
    assert [m["text_ru"] for m in client_messages(nodes, conversation_signal_ids={1, 2})] == ["Ответ1", "Ответ2"]
    assert [m["text_ru"] for m in client_messages(nodes)] == ["Ответ1"]


def test_empty_env_value_does_not_turn_comment_into_a_model_path(tmp_path, monkeypatch):
    monkeypatch.delenv("STT_MODEL_PATH", raising=False)
    path = tmp_path / ".env"
    path.write_text("STT_MODEL_PATH=  # локальная модель\n")
    assert read_env_file(path)["STT_MODEL_PATH"] == ""
    write_env_file(path, {"STT_MODEL_PATH": None})
    assert Settings(_env_file=path).stt_model_path in (None, "")
    assert "# локальная модель" in path.read_text()


@pytest.mark.parametrize("raw", ["#literal", '"#literal"', ' "#literal"'])
def test_env_hash_value_is_not_an_unquoted_whitespace_comment(tmp_path, raw):
    path = tmp_path / ".env"
    path.write_text(f"APP_SECRET={raw}\n")
    assert read_env_file(path)["APP_SECRET"] == "#literal"


async def test_matching_fault_scope_still_rejects_stale_hitl_before_request(monkeypatch):
    monkeypatch.setattr(nodes, "_native_service_scope", AsyncMock(return_value=None))
    monkeypatch.setattr(nodes, "_hitl_incident_id", AsyncMock(return_value=7))
    monkeypatch.setattr(nodes.proactive, "causal_fault", AsyncMock(return_value=None))
    request = AsyncMock(side_effect=AssertionError("stale scope must not request approval"))
    monkeypatch.setattr(nodes.wt, "request_human_decision", request)
    state = {
        "decision": {"incident_action": "link_existing", "link_incident_id": 7},
        "signal": {"id": 1, "received_sim": "2026-11-09T09:00:00Z"},
        "classification": {"error_code": "NOTIF-DELAY"},
        "context": {"hints": {"fault_id": 3, "error_code": "NOTIF-DELAY"}},
        "client": {"client_id": 10},
        "actions": [],
    }
    deps = SimpleNamespace(ctx=SimpleNamespace(run_id=2, conn=object(), fetchone=AsyncMock(return_value=None)))
    with pytest.raises(ValueError, match="причинная связь с incident устарела"):
        await nodes.wait_human(state, deps)
    request.assert_not_awaited()
