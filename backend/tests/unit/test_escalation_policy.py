"""T-213: шесть веток уже написанной политики эскалации и уточнения. Пороги не меняются."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import policies as pol
from app.agent.nodes import _context_for_prompt, _policy_context
from app.agent.tools import read

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
    assert pol.needs_human(classification, pol.PolicyContext()) is None
    assert pol.needs_human(classification, pol.PolicyContext(segment="ultra_vip")) == "ultra_vip"
    assert pol.needs_human(classification, pol.PolicyContext(repeat_count=3)) == "repeat_3plus"


async def test_repeat_hitl_uses_exact_count_and_keeps_legacy_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    fault = {
        **_BASE,
        "signal_type": "tech_fault",
        "product": "debit_card",
        "system": "processing",
        "error_code": "PROC-DOUBLE-DEBIT",
    }
    counter = AsyncMock(return_value=0)
    monkeypatch.setattr(read, "count_same_cause", counter)
    state = {
        "signal": {"id": 9},
        "client": {"client_id": 7},
        "classification": fault,
        "normalization": {},
        "context": {"client_history": {"last_types": ["tech_fault"] * 5, "history_scope": "run_and_baseline_v1"}},
    }
    deps = SimpleNamespace(ctx=object())
    context = await _policy_context(state, deps)  # type: ignore[arg-type]
    assert context.repeat_count == 1 and pol.needs_human(fault, context) is None
    counter.assert_awaited_once_with(deps.ctx, 7, 9, fault, None)
    counter.return_value = 2
    context = await _policy_context(state, deps)  # type: ignore[arg-type]
    assert context.repeat_count == 3 and pol.needs_human(fault, context) == "repeat_3plus"
    counter.reset_mock()
    del state["context"]["client_history"]["history_scope"]
    assert (await _policy_context(state, deps)).repeat_count == 6  # type: ignore[arg-type]
    counter.assert_not_awaited()


async def test_ambiguous_history_does_not_invent_a_cause_or_repeat_gratitude() -> None:
    context = SimpleNamespace(fetchone=AsyncMock())
    for value in (
        {"signal_type": "tech_fault"},
        {"signal_type": "gratitude", "system": "processing", "error_code": "PROC-DOUBLE-DEBIT"},
    ):
        assert await read.count_same_cause(context, 7, 9, value, None) == 0  # type: ignore[arg-type]
    context.fetchone.assert_not_awaited()


def test_history_scope_marker_does_not_change_prompt_or_replay_identity() -> None:
    state = {"context": {"client_history": {"signals_14d": 2, "last_types": ["tech_fault"]}}}
    before = deepcopy(_context_for_prompt(state))  # type: ignore[arg-type]
    state["context"]["client_history"]["history_scope"] = "run_and_baseline_v1"
    assert _context_for_prompt(state) == before  # type: ignore[arg-type]
    assert state["context"]["client_history"]["history_scope"] == "run_and_baseline_v1"


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
