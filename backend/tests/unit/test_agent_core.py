"""B04: политики HITL/эскалации, SLA/приоритет, промпты, схема графа, движок правил, нормализатор входа."""

from __future__ import annotations

import datetime as dt

from app.agent import policies as pol
from app.agent import sla
from app.agent.graph import GRAPH_SPEC, NODES
from app.agent.nodes import prune, regex_hints
from app.agent.prompts import load, prompt_version
from app.contracts.registry import deref, validate
from app.ingest.normalizer import from_api_signal, from_sim_event
from app.rules.engine import evaluate
from app.sim.clock import MSK

BASE = {
    "signal_type": "tech_fault",
    "confidence": 0.9,
    "criticality": "medium",
    "flags": [],
    "problem_summary": {"severity": "medium"},
}


def test_needs_human_branches() -> None:
    assert pol.needs_human(BASE, pol.PolicyContext()) is None
    assert pol.needs_human({**BASE, "confidence": 0.5}, pol.PolicyContext()) == "low_confidence"
    assert pol.needs_human(BASE, pol.PolicyContext(segment="ultra_vip")) == "ultra_vip"
    assert pol.needs_human({**BASE, "signal_type": "legal_regulatory"}, pol.PolicyContext()) == "legal_regulatory"
    assert (
        pol.needs_human({**BASE, "signal_type": "fraud_suspicion"}, pol.PolicyContext(amount_rub=60_000))
        == "fraud_amount"
    )
    assert pol.needs_human({**BASE, "signal_type": "fraud_suspicion"}, pol.PolicyContext(amount_rub=1_000)) is None
    assert pol.needs_human(BASE, pol.PolicyContext(repeat_count=3)) == "repeat_3plus"
    assert pol.needs_human(BASE, pol.PolicyContext(gift_code="lounge_pass")) == "partner_privilege"
    assert (
        pol.needs_human(
            {**BASE, "signal_type": "tariff_terms", "confidence": 0.8}, pol.PolicyContext(rule_based_type="tech_fault")
        )
        == "classifier_conflict"
    )


def test_escalation_and_clarification() -> None:
    norm = {"negativity": 85, "hidden_negativity": {"churn_threat": {"present": True}}, "entities": {}}
    assert pol.needs_escalation(norm, BASE, pol.PolicyContext()) is not None
    assert pol.needs_escalation({"negativity": 10, "hidden_negativity": {}}, BASE, pol.PolicyContext()) is None
    assert (
        pol.needs_escalation({"negativity": 10, "hidden_negativity": {}}, BASE, pol.PolicyContext(signals_7d=3))
        is not None
    )
    assert pol.needs_clarification({**BASE, "confidence": 0.5}, {"entities": {}}, already_asked=False)
    assert not pol.needs_clarification({**BASE, "confidence": 0.5}, {"entities": {}}, already_asked=True)
    assert not pol.needs_clarification(BASE, {"entities": {"amount_rub": 100}}, already_asked=False)
    assert pol.forbidden_phrases("Гарантируем возврат, это ваша вина") and not pol.forbidden_phrases(
        "Разбираемся, вернёмся с ответом"
    )
    assert pol.human_options("ultra_vip")[0]["code"] == "accept" and len(pol.human_options("x")) >= 2


def test_sla_priority_gift() -> None:
    fri = dt.datetime(2026, 11, 6, 9, 0, tzinfo=MSK)
    s = sla.sla_for("easy", "high", fri)
    assert (s["fix_days"], s["take_hours"]) == (1, 2) and dt.datetime.fromisoformat(s["due_sim"]).weekday() == 0
    hard = sla.sla_for("hard", "low", fri)
    assert hard["fix_days"] == 10 and len(hard["report_due_sims"]) == 3
    assert sla.effective_criticality("low", ["mass_impact"], "mass", "tech_fault", 5) in ("medium", "high")
    assert sla.effective_criticality("medium", [], "vip", "tech_fault") == "high"
    assert sla.priority("high", 90, "vip", ["churn_intent"]) == 1 and sla.priority("low", 0, "mass", []) == 4
    g = sla.pick_gift("high", "vip", ["repeat"])
    assert g is not None and 300 <= g["points"] <= 1000
    assert sla.pick_gift("low", "mass", []) is None or sla.pick_gift("low", "mass", [])["points"] == 300


def test_prompts_and_graph_spec() -> None:
    for name in ("system", "normalize", "classify", "decide"):
        p = load(name)
        assert p.meta["version"] and p.body
    assert prompt_version().startswith("v1")
    assert "{{ text }}" not in load("classify").render(
        text="x", teams="", fewshot="", context="", normalization="", channel="chat"
    )
    assert validate({}, "agent/decision")  # пустой объект невалиден
    ids = {n["id"] for n in GRAPH_SPEC["nodes"]}
    assert set(NODES) <= ids
    assert all(e["from"] in ids and e["to"] in ids for e in GRAPH_SPEC["edges"])


def test_prune_and_regex_hints() -> None:
    schema = deref("agent/classification")
    out = prune(
        {"signal_type": "tech_fault", "unknown_field": 1, "problem_summary": {"problem": "x", "extra": 2}}, schema
    )
    assert "unknown_field" not in out and "extra" not in out["problem_summary"]
    h = regex_hints("Списали 1 250 руб по QR, карта ****4512, промо PROMO-DEP-14")
    assert h == {
        "amount_rub": 1250.0,
        "masked_card_last4": "4512",
        "promo_code": "PROMO-DEP-14",
        "operation_hint": "qr_payment",
    }


def test_rules_engine_dsl() -> None:
    cond = {
        "all": [
            {"field": "operation.op_type", "eq": "card_payment"},
            {"field": "operation.method", "eq": "qr_sbp"},
            {"field": "operation.fee_amount", "gt": 0},
            {"field": "tariff.fee_pct", "eq": 0},
        ]
    }
    ctx = {"operation": {"op_type": "card_payment", "method": "qr_sbp", "fee_amount": 138.0}, "tariff": {"fee_pct": 0}}
    assert evaluate(cond, ctx)
    assert not evaluate(cond, {**ctx, "operation": {**ctx["operation"], "fee_amount": 0}})
    assert evaluate({"any": [{"field": "a", "eq": 1}, {"not": {"field": "a", "eq": 2}}]}, {"a": 3})
    assert not evaluate({"field": "x", "within_promo": "PROMO"}, {})


def test_unified_message_from_api_and_sim() -> None:
    m = from_api_signal({"channel_code": "chat", "client_id": 5, "text": "Привет"})
    assert validate({k: v for k, v in m.items() if v is not None}, "ingest/unified_message") == []
    m2 = from_sim_event(
        {
            "signal_id": 1,
            "channel": "social",
            "client_id": None,
            "external_contact": {"nick": "@a", "region_code": "77"},
            "text": "t",
            "received_sim": "2026-11-09T10:00:00+03:00",
            "origin": "sim",
        }
    )
    assert validate(m2, "ingest/unified_message") == [] and m2["geo"]["region_code"] == "77"
