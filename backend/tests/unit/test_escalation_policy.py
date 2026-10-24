"""T-213: шесть веток уже написанной политики эскалации и уточнения. Пороги не меняются."""

from __future__ import annotations

from app.agent import policies as pol

_QUIET = {"negativity": 10, "hidden_negativity": {}, "entities": {}, "intents": []}
_BASE = {
    "signal_type": "service_quality",
    "confidence": 0.9,
    "flags": [],
    "sentiment": "neutral",
    "problem_summary": {},
}


def test_churn_threat_at_negativity_80() -> None:
    churn = {"negativity": 80, "hidden_negativity": {"churn_threat": {"present": True}}, "intents": []}
    assert pol.needs_escalation(churn, _BASE, pol.PolicyContext()) == "churn_threat_high_negativity"
    below = {"negativity": 79, "hidden_negativity": {"churn_threat": {"present": True}}, "intents": []}
    assert pol.needs_escalation(below, _BASE, pol.PolicyContext()) is None


def test_repeat_and_negative_sentiment() -> None:
    classification = {**_BASE, "flags": ["repeat"], "sentiment": "negative"}
    assert pol.needs_escalation(_QUIET, classification, pol.PolicyContext()) == "repeat_negative"
    assert (
        pol.needs_escalation(_QUIET, {**_BASE, "flags": ["repeat"], "sentiment": "neutral"}, pol.PolicyContext())
        is None
    )


def test_critical_severity() -> None:
    classification = {**_BASE, "problem_summary": {"severity": "critical"}}
    assert pol.needs_escalation(_QUIET, classification, pol.PolicyContext()) == "critical_severity"


def test_three_signals_in_7_days() -> None:
    assert pol.needs_escalation(_QUIET, _BASE, pol.PolicyContext(signals_7d=3)) == "three_signals_7d"
    assert pol.needs_escalation(_QUIET, _BASE, pol.PolicyContext(signals_7d=2)) is None


def test_clarification_low_confidence_or_empty_entities() -> None:
    low = {**_BASE, "confidence": 0.59, "signal_type": "service_quality", "entities": {"product": "debit_card"}}
    assert pol.needs_clarification(low, {"entities": {"product": "debit_card"}}, already_asked=False)
    tariff = {**_BASE, "confidence": 0.9, "signal_type": "tariff_terms", "entities": {}}
    assert pol.needs_clarification(tariff, {"entities": {}}, already_asked=False)
    fault = {**_BASE, "confidence": 0.9, "signal_type": "tech_fault", "entities": {}}
    assert pol.needs_clarification(fault, {"entities": {}}, already_asked=False)
    filled = {**_BASE, "confidence": 0.9, "signal_type": "tech_fault", "product": "debit_card"}
    assert not pol.needs_clarification(filled, {"entities": {}}, already_asked=False)


def test_second_clarification_in_a_row_is_forbidden() -> None:
    low = {**_BASE, "confidence": 0.1, "signal_type": "tech_fault", "entities": {}}
    assert not pol.needs_clarification(low, {"entities": {}}, already_asked=True)
