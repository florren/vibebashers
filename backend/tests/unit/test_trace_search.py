"""Grammar, causal ordering, privacy and bounded projection regressions."""

from __future__ import annotations

import json

import pytest

from app.contracts.events.trace.journey import Journey as JourneyResponse
from app.contracts.events.trace.trace_response import TraceResponse
from app.search.grammar import PREFIXES, parse
from app.trace.assembler import causal_order, pending_steps, render, terminal_for
from app.trace.journey import build_journey, client_messages
from app.trace.privacy import mask
from app.trace.projections import project
from app.trace.relations import MATRIX, TYPES

TS = "2026-10-01T10:00:00+00:00"


def node(kind: str, id: int = 1, **data):
    return {
        "kind": kind,
        "scope_id": 1,
        "data": {"id": id, "created_at": TS, "created_sim": TS, "public_id": f"{kind}-{id}", "status": "new", **data},
    }


@pytest.mark.parametrize("prefix,kind", PREFIXES.items())
def test_prefixes(prefix, kind):
    p = parse(f"{prefix.lower()} — 000123".replace(" — ", "-"))
    assert p["kind"] == kind
    assert p["mode"] == "id"
    assert p == parse(f"{prefix} 123")


@pytest.mark.parametrize(
    "q,kind,mode",
    [
        ("00042", "number", "id"),
        ("RULE-QR-FEE-001", "rule", "id"),
        ("PROC-QR-FEE-CHARGED", "error_code", "id"),
        ("@tester", None, "hints"),
        ("**** 4512", None, "hints"),
        ("+7 900 ***-**-12", None, "hints"),
        ("комиссия", None, "text"),
        ("550e8400-e29b-41d4-a716-446655440000", "correlation", "id"),
        ("abcdefghijklmnopqrstuvwxyz", "tracking", "id"),
    ],
)
def test_grammar(q, kind, mode):
    assert parse(q)["kind"] == kind
    assert parse(q)["mode"] == mode


def test_relations_complete():
    assert set(MATRIX) == set(TYPES)
    assert {"post", "transcript", "operation", "fault", "ledger", "ingest"} <= set(MATRIX["signal"]["before"])
    assert {"notification", "task", "followup", "economics", "reaction"} <= set(MATRIX["incident"]["after"])


def test_no_raw_prompts_or_contacts():
    e = project(
        node(
            "step",
            node="decide",
            seq=2,
            run_id=3,
            prompt="secret",
            response_raw="secret",
            output={"prompt": "secret"},
            model="replay/GigaChat-3-Pro",
            latency_ms=20,
        ),
        "after",
    )
    assert "secret" not in json.dumps(e)
    assert e["badges"]["llm_source"] == "replay"
    assert e["links"]["engine_step"] == "/engine/3?step=2"
    masked = mask("карта 4111 1111 1111 4512 телефон +7 900 123-45-67 @realuser me@example.org")
    assert "123-45-67" not in masked and "@realuser" not in masked and "me@example.org" not in masked
    assert "**** 4512" in masked


def test_causality_wins_over_time_and_cycle_is_bounded():
    a, b = node("signal", 1, received_sim="2026-10-02T00:00:00Z"), node("incident", 2, status="closed")
    edges = [{"from": "EVT-signal:1", "to": "EVT-incident:2", "relation_ru": "Причина"}]
    assert causal_order([b, a], edges) == [a, b]
    assert len(causal_order([b, a], [*edges, {"from": "EVT-incident:2", "to": "EVT-signal:1"}])) == 2
    result = render(a, [], [b], edges)
    assert result["after"][0]["order_warning"]
    TraceResponse.model_validate(result)


def test_fanout_and_pending_not_facts():
    subject = node("incident", status="new", sla_due_sim=TS)
    signals = [dict(node("signal", i), parent="incident:1") for i in range(2, 122)]
    result = render(subject, [], signals, [])
    assert result["groups"][0]["count"] == 120
    assert len(result["after"]) == 3
    assert not result["terminal"]["reached"]
    assert result["pending"][0]["kind_ru"] == "Срок SLA"
    assert pending_steps([node("human_decision", decision=None)])[0]["due_sim"] is None
    TraceResponse.model_validate(result)


def test_journey_delivered_messages_and_waiting():
    subject = node("signal", status="awaiting_human")
    hitl = node("human_decision", decision=None, requested_at=TS, requested_sim=TS)
    queued = node("notification", status="queued", recipient_type="client", body="не отправлено", channel_code="push")
    internal = node(
        "notification",
        2,
        status="sent",
        recipient_type="team",
        sent_at=TS,
        body="секрет команды",
        channel_code="internal",
    )
    delivered = node(
        "notification",
        3,
        status="delivered",
        recipient_type="client",
        sent_at=TS,
        sent_sim=TS,
        body="Принято",
        channel_code="push",
    )
    nodes = [subject, hitl, queued, internal, delivered]
    lane = client_messages(nodes)
    assert [m["text_ru"] for m in lane] == ["Принято"]
    trace = render(subject, [], nodes[1:], [])
    journey = build_journey(trace, nodes)
    assert journey["stages"][4]["status"] == "waiting_human"
    JourneyResponse.model_validate(journey)


@pytest.mark.parametrize(
    "kind,status", [("incident", "closed"), ("signal", "noise"), ("task", "done"), ("escalation", "resolved")]
)
def test_terminal_by_object_kind(kind, status):
    assert terminal_for(node(kind, status=status), [])["reached"]


def test_early_notification_does_not_skip_unfinished_work():
    subject = node("signal", status="processing")
    step = node("step", node="normalize", seq=1, run_id=1)
    notice = node(
        "notification",
        status="sent",
        recipient_type="client",
        sent_at=TS,
        body="Приняли обращение",
        channel_code="push",
    )
    nodes = [subject, step, notice]
    journey = build_journey(render(subject, [], nodes[1:], []), nodes)
    assert journey["stages"][1]["status"] == "active"
    assert journey["stages"][4]["status"] == "pending"
