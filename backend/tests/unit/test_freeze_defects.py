"""Регрессии дефектов, воспроизведённых при приёмке стенда."""

import datetime as dt

import pytest

from app.api.envfile import read_env_file, write_env_file
from app.config import Settings
from app.contracts.registry import validate
from app.llm.mock import analyze
from app.sim.clock import MSK
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
