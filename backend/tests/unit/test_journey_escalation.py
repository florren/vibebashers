"""Неблокирующая эскалация не останавливает путь на стадии решения человека."""

from __future__ import annotations

from typing import Any

import pytest

from app.contracts.events.trace.journey import Journey as JourneyResponse
from app.trace.assembler import render
from app.trace.journey import build_journey

TS = "2026-10-29T12:08:18+00:00"


def record(kind: str, **data: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "scope_id": 1,
        "data": {"id": 1, "public_id": f"{kind}-1", "created_at": TS, "created_sim": TS, **data},
    }


def escalation() -> dict[str, Any]:
    return record(
        "human_decision",
        decision=None,
        requested_at=TS,
        requested_sim=TS,
        agent_proposal={"kind": "escalation", "escalation_id": 1},
    )


@pytest.mark.parametrize("status", ["deferred", "closed"])
def test_parallel_escalation_keeps_execution_and_delivered_reply(status: str) -> None:
    subject = record("signal", status=status, received_at=TS)
    followup = record("followup", status="scheduled", wake_sim=TS)
    notice = record(
        "notification",
        status="sent",
        recipient_type="client",
        channel_code="chat",
        sent_at=TS,
        body="Проверим обработку платежа по дебетовой карте.",
    )
    nodes = [subject, escalation(), followup, notice]
    trace = render(subject, [], nodes[1:], [])
    result = build_journey(trace, nodes)
    stages = {stage["stage"]: stage for stage in result["stages"]}
    assert stages["decision"]["status"] == "done"
    assert stages["execution"]["status"] == ("done" if status == "closed" else "active")
    assert result["summary"]["outcome_ru"] != "Ожидаем решения человека"
    assert stages["decision"]["events"][0]["kind"] == "human_request"
    # Запрос руководителю остаётся в следе, а доставленный ответ — в клиентской ленте.
    assert any(item["object_ref"]["kind"] == "human_decision" for item in trace["pending"])
    assert result["client_lane"][0]["text_ru"] == notice["data"]["body"]
    JourneyResponse.model_validate(result)


@pytest.mark.parametrize("proposal", [{}, {"needs_human": True}])
def test_blocking_human_request_still_stops_journey_with_parallel_escalation(proposal: dict[str, Any]) -> None:
    subject = record("signal", status="awaiting_human")
    blocking = record("human_decision", id=2, decision=None, requested_at=TS, requested_sim=TS, agent_proposal=proposal)
    nodes = [subject, escalation(), blocking]
    result = build_journey(render(subject, [], nodes[1:], []), nodes)
    assert result["stages"][4]["status"] == "waiting_human"
    assert result["summary"]["outcome_ru"] == "Ожидаем решения человека"
    JourneyResponse.model_validate(result)
