"""Чистое ядро: реальные справочники, явная тестовая policy, без БД/LLM/runtime wiring."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.contracts.enums import ClientState
from app.contracts.events.behavior.psychotype_params import PsychotypeParams
from app.sim.behavior.model import BehaviorModel, BehaviorPolicy, CareEvidence, Snapshot, hazard
from app.sim.rng import SimRng

DATA = yaml.safe_load((Path(__file__).resolve().parents[3] / "data/psychotypes.yaml").read_text())["psychotypes"]
NOW = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)


def scoring(previous: float, evidence: CareEvidence, weights: Mapping[str, float]) -> float:
    # Только тестовый пример стратегии, не новое правило продукта.
    if evidence.kind == "proactive_notice":
        return min(1.0, previous + weights["proactive"])
    if evidence.kind == "sla_breach":
        return max(0.0, previous - weights["sla"])
    return previous


def params(code: str = "loyal_pragmatic") -> PsychotypeParams:
    return PsychotypeParams.model_validate(DATA[code]["params"])


def model(code: str = "loyal_pragmatic") -> BehaviorModel:
    return BehaviorModel(params(code), BehaviorPolicy(1.0, 0.7, scoring))


def snapshot(state: ClientState = ClientState.CALM) -> Snapshot:
    return Snapshot(state, 0.5, 0, False)


@pytest.mark.parametrize("code", DATA)
def test_complaints_per_psychotype_real_catalog(code: str) -> None:
    core, rng = model(code), SimRng(161)
    outcomes = [core.affected(snapshot(), NOW, rng) for _ in range(1000)]
    fraction = sum(x.complain_due is not None for x in outcomes) / len(outcomes)
    assert abs(fraction - core.params.p_complain) <= 0.03
    if code == "silent_churner":
        assert fraction <= 0.15
    lo, hi = (item.root for item in core.params.complain_delay_min)
    assert all(
        NOW + dt.timedelta(minutes=lo) <= x.complain_due <= NOW + dt.timedelta(minutes=hi)
        for x in outcomes
        if x.complain_due is not None
    )
    assert all(not x.silent_decline for x in outcomes if x.complain_due is not None)


def test_hazard_exact_formula_without_silent_clamp() -> None:
    policy = BehaviorPolicy(2.5, 0.7, scoring)
    state = Snapshot(ClientState.WAITING, 0.25, 3, True)
    p = params()
    assert hazard(p, policy, state, repeat=3) == pytest.approx(
        p.base_churn_hazard * 2.5 * 2.5 * 1.8 * (1 - p.care_sensitivity * 0.25)
    )
    high = BehaviorPolicy(1000, 0.7, scoring)
    result = BehaviorModel(p, high).sla_tick(state, SimRng(1), repeat=3)
    assert result.raw_hazard > 1
    assert result.transition.after.state == ClientState.CHURN_INTENT
    assert result.triggered
    second = BehaviorModel(p, high).sla_tick(result.transition.after, SimRng(1), repeat=3)
    assert second.triggered
    assert second.transition.after.state != ClientState.CHURNED


def test_care_strategy_explicit_growth_and_sla_decline() -> None:
    core = model()
    initial = snapshot(ClientState.WAITING)
    first = core.observe_care(initial, CareEvidence("proactive_notice", 1, NOW)).after
    second = core.observe_care(first, CareEvidence("sla_breach", 2, NOW)).after
    assert first.care_score > initial.care_score
    assert second.care_score < first.care_score
    assert second.sla_breached
    assert initial.care_score == 0.5  # Вход не изменяется.


def test_state_journey_and_retention_threshold() -> None:
    core = BehaviorModel(params().model_copy(update={"p_complain": 1.0}), BehaviorPolicy(1, 0.7, scoring))
    affected = core.affected(snapshot(), NOW, SimRng(1)).transition.after
    complained = core.complaint_due(affected).after
    waiting = core.signal_sent(complained).after
    assert waiting.state == ClientState.WAITING
    assert core.closure(waiting) is None  # неопределённый исход не выдумывается
    retained = core.closure(replace(waiting, care_score=0.7))
    assert retained is not None and retained.after.state == ClientState.RETAINED


@pytest.mark.parametrize("escalation,state", [(0, ClientState.ASKS_AGAIN), (1, ClientState.ESCALATES)])
def test_repeat_counts_and_escalates(escalation: float, state: ClientState) -> None:
    core = BehaviorModel(
        params().model_copy(update={"repeat_prob": 1.0, "escalation_prob": escalation}), BehaviorPolicy(1, 0.7, scoring)
    )
    result = core.repeat(snapshot(ClientState.WAITING), SimRng(1))
    assert result.after.state == state and result.after.repeat_count == 1
    assert core.signal_sent(result.after).after.state == ClientState.WAITING


def test_zero_probabilities_and_no_repeat() -> None:
    p = params().model_copy(
        update={"p_complain": 0.0, "silent_decline_prob": 0.0, "repeat_prob": 0.0, "base_churn_hazard": 0.0}
    )
    core = BehaviorModel(p, BehaviorPolicy(1, 0.7, scoring))
    result = core.affected(snapshot(), NOW, SimRng(1))
    assert result.complain_due is None and not result.silent_decline
    waiting = snapshot(ClientState.WAITING)
    assert core.repeat(waiting, SimRng(1)).after == waiting
    assert core.sla_tick(waiting, SimRng(1), repeat=0).transition.after == waiting


def test_rng_state_round_trip_identical_decisions() -> None:
    rng = SimRng(161)
    core = model("anxious")
    for _ in range(10):
        core.affected(snapshot(), NOW, rng)
    saved = rng.dump_state()
    first = [core.affected(snapshot(), NOW, rng) for _ in range(30)]
    final = rng.dump_state()
    resumed = SimRng(999)
    resumed.load_state(saved)
    assert [core.affected(snapshot(), NOW, resumed) for _ in range(30)] == first
    assert resumed.dump_state() == final


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_policy_invalid_multiplier(value: float) -> None:
    with pytest.raises(ValueError):
        BehaviorPolicy(value, 0.7, scoring)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_care_strategy_invalid_output_rejected(value: float) -> None:
    core = BehaviorModel(params(), BehaviorPolicy(1, 0.7, lambda *_: value))
    with pytest.raises(ValueError, match="care_strategy result"):
        core.observe_care(snapshot(), CareEvidence("gift", 1, NOW))


def test_required_policy_and_parameters_no_fallback() -> None:
    with pytest.raises(TypeError):
        BehaviorPolicy()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="care_weights"):
        BehaviorModel(params().model_copy(update={"care_weights": None}), BehaviorPolicy(1, 0.7, scoring))
    with pytest.raises(ValueError, match="reversed"):
        raw = params().model_dump()
        raw["complain_delay_min"] = [5, 1]
        BehaviorModel(PsychotypeParams.model_validate(raw), BehaviorPolicy(1, 0.7, scoring))


def test_invalid_source_states_and_timestamps() -> None:
    core = model()
    with pytest.raises(ValueError):
        core.complaint_due(snapshot())
    with pytest.raises(ValueError):
        core.signal_sent(snapshot())
    with pytest.raises(ValueError):
        core.repeat(snapshot(), SimRng(1))
    with pytest.raises(ValueError):
        core.sla_tick(snapshot(), SimRng(1), repeat=0)
    with pytest.raises(ValueError):
        core.affected(snapshot(ClientState.AFFECTED), NOW, SimRng(1))
    with pytest.raises(ValueError):
        core.affected(snapshot(), NOW.replace(tzinfo=None), SimRng(1))
    with pytest.raises(ValueError):
        core.closure(snapshot(ClientState.CHURNED))
    with pytest.raises(ValueError):
        core.observe_care(snapshot(ClientState.CHURNED), CareEvidence("gift", 1, NOW))
    with pytest.raises(ValueError):
        CareEvidence("gift", 0, NOW)


def test_weights_validation_and_read_only_strategy_input() -> None:
    raw = params().model_dump()
    raw["care_weights"] = {"proactive": 0.5}
    with pytest.raises(ValueError, match="sum to 1"):
        BehaviorModel(PsychotypeParams.model_validate(raw), BehaviorPolicy(1, 0.7, scoring))
    raw["care_weights"] = {"proactive": -1, "sla": 2}
    with pytest.raises(ValueError, match="nonnegative"):
        BehaviorModel(PsychotypeParams.model_validate(raw), BehaviorPolicy(1, 0.7, scoring))
    core = model()
    with pytest.raises(TypeError):
        core.weights["proactive"] = 0  # type: ignore[index]


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_invalid_snapshot_and_threshold(value: float) -> None:
    with pytest.raises(ValueError):
        Snapshot(ClientState.CALM, value, 0, False)
    with pytest.raises(ValueError):
        BehaviorPolicy(1, value, scoring)


def test_hazard_repeat_interpretation_is_required() -> None:
    p, policy, state = params(), BehaviorPolicy(1, 0.7, scoring), snapshot(ClientState.WAITING)
    with pytest.raises(TypeError):
        hazard(p, policy, state)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        hazard(p, policy, state, repeat=-1)
    assert hazard(p, policy, state, repeat=3) > hazard(p, policy, state, repeat=1)


@pytest.mark.parametrize("value", [True, False, 1.5, "1", None, 0, -1])
def test_evidence_requires_positive_integer_source(value: object) -> None:
    with pytest.raises(ValueError):
        CareEvidence("gift", value, NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False, 1.5, "1", None, -1])
def test_snapshot_requires_integer_repeat_count(value: object) -> None:
    with pytest.raises(ValueError):
        Snapshot(ClientState.WAITING, 0.5, value, False)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["calm", "unknown", None, True, 1])
def test_snapshot_requires_generated_state(value: object) -> None:
    with pytest.raises(ValueError, match="ClientState"):
        Snapshot(value, 0.5, 0, False)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False, "0.5", None])
def test_policy_and_care_reject_boolean_or_nonnumeric(value: object) -> None:
    with pytest.raises(ValueError):
        BehaviorPolicy(value, 0.7, scoring)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        BehaviorPolicy(1, value, scoring)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Snapshot(ClientState.WAITING, value, 0, False)  # type: ignore[arg-type]
    core = BehaviorModel(params(), BehaviorPolicy(1, 0.7, lambda *_: value))  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError):
        core.observe_care(snapshot(), CareEvidence("gift", 1, NOW))


def test_explicit_repeat_boolean_supported_pending_policy_review() -> None:
    p, policy, state = params(), BehaviorPolicy(1, 0.7, scoring), snapshot(ClientState.WAITING)
    assert hazard(p, policy, state, repeat=True) == hazard(p, policy, state, repeat=1)
    assert hazard(p, policy, state, repeat=False) == hazard(p, policy, state, repeat=0)


def test_zero_hazard_in_intent_requests_no_account_closure() -> None:
    core = BehaviorModel(params(), BehaviorPolicy(0, 0.7, scoring))
    initial = snapshot(ClientState.CHURN_INTENT)
    result = core.sla_tick(initial, SimRng(1), repeat=0)
    assert not result.triggered
    assert result.transition.after == initial
    assert not hasattr(result, "closure_requested")
