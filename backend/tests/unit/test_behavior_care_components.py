"""T-161: все компоненты и sticky факты воспроизводимы из явного состояния."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.sim.behavior.care import (
    CareComponents,
    CareContext,
    CarePolicy,
    CareState,
    CommunicationEvidence,
    GiftEvidence,
    SlaEvidence,
    evaluate_care,
)

AT = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)
CONTEXT = CareContext(AT, AT + dt.timedelta(minutes=10), 10.0)
WEIGHTS = {
    key: value
    for key, value in zip(
        ("proactive", "speed", "sla", "gift_fit", "tone", "explanation"), (0.1, 0.2, 0.2, 0.1, 0.2, 0.2), strict=True
    )
}
RAW = yaml.safe_load((Path(__file__).resolve().parents[3] / "data/behavior/demo_policy.review.yaml").read_text())
POLICY = CarePolicy(
    RAW["care"]["components"]["explanation"]["eligible_template_score"],
    frozenset(RAW["care"]["first_reply_excluded_templates"]),
)
EMPTY = CareState(CareComponents())


def communication(**changes):
    values = dict(
        source_id=1,
        at=AT + dt.timedelta(minutes=20),
        delivery_status="sent",
        customer_attributed=True,
        valid=True,
        proactive=False,
        template_code="resolved",
        template_fields_present=True,
    )
    return CommunicationEvidence(**(values | changes))


def apply(evidence, state=EMPTY, context=CONTEXT, weights=WEIGHTS):
    return evaluate_care(state, evidence, context=context, policy=POLICY, weights=weights)


def test_exact_components_score_and_rounding_after_sum() -> None:
    result = apply(communication())
    assert result.state.components == CareComponents(speed=1.0, tone=1.0, explanation=1.0)
    assert result.score == Decimal(".600")
    assert result.state.first_reply_at == AT + dt.timedelta(minutes=20)
    # Округление один раз: шесть промежуточных округлений дали бы другой результат.
    state = CareState(CareComponents(**{key: 0.0005 for key in WEIGHTS}))
    assert apply(communication(delivery_status="queued"), state).score == Decimal(".001")


def test_duplicate_and_later_reply_never_stack_or_rewrite_first_delay() -> None:
    late = communication(at=AT + dt.timedelta(minutes=25))
    first = apply(late)
    assert first.state.components.speed == 0.5
    assert apply(late, first.state) == first
    later = apply(communication(source_id=2, at=AT + dt.timedelta(minutes=40)), first.state)
    assert later == first
    # Поздно доставленный более ранний факт восстанавливает настоящий первый ответ.
    earlier = apply(communication(source_id=3, at=AT + dt.timedelta(minutes=20)), first.state)
    assert earlier.state.components.speed == 1


def test_proactive_requires_actual_causal_time_strictly_before_complaint() -> None:
    assert apply(communication(proactive=True, at=AT + dt.timedelta(minutes=5))).state.components.proactive == 1
    assert apply(communication(proactive=True, at=CONTEXT.first_complaint_at)).state.components.proactive == 0
    assert apply(communication(proactive=True, at=AT - dt.timedelta(seconds=1))) == apply(
        communication(delivery_status="queued")
    )
    assert (
        apply(
            communication(proactive=True), context=replace(CONTEXT, first_complaint_at=None)
        ).state.components.proactive
        == 1
    )


def test_invalid_message_adds_no_positive_credit_and_tone_is_sticky() -> None:
    invalid = communication(valid=False, proactive=True)
    result = apply(invalid)
    assert result.state.components == CareComponents()
    assert result.state.tone_violated
    good = apply(communication(), result.state)
    assert good.state.components.tone == 0
    assert good.state.components.speed == 1 and good.state.components.explanation == 1
    earlier_good = apply(communication())
    bad_after = apply(invalid, earlier_good.state)
    assert bad_after.score < earlier_good.score
    assert bad_after.state.components.speed == earlier_good.state.components.speed


@pytest.mark.parametrize("changes", [{"delivery_status": "queued"}, {"customer_attributed": False}])
def test_unsent_unattributed_message_has_no_effect(changes) -> None:
    result = apply(communication(**changes))
    assert result.state == EMPTY and result.score == 0


@pytest.mark.parametrize("template", ["dm_invite", "gift_offer", "team_notice"])
def test_excluded_templates_cannot_be_first_reply(template) -> None:
    result = apply(communication(template_code=template))
    assert result.state.first_reply_at is None and result.state.components.speed == 0
    assert result.state.components.explanation == 0


def test_unknown_missing_fields_and_no_signal_never_invent_explanation_or_speed() -> None:
    assert apply(communication(template_code="unknown")).state.components.explanation == 0
    assert apply(communication(template_fields_present=False)).state.components.explanation == 0
    assert apply(communication(), context=replace(CONTEXT, first_complaint_at=None)).state.components.speed == 0
    assert apply(communication(at=AT + dt.timedelta(minutes=40))).state.components.speed == 0


def test_sla_breach_stays_zero_despite_later_progress() -> None:
    good = apply(SlaEvidence(1, AT, True, False))
    assert good.state.components.sla == 1
    bad = apply(SlaEvidence(2, AT, True, True), good.state)
    assert bad.state.sla_breached and bad.state.components.sla == 0
    assert apply(SlaEvidence(3, AT, True, False), bad.state).state.components.sla == 0
    assert apply(SlaEvidence(1, AT, False, False)).state.components.sla == 0


def test_gift_only_issued_done_and_sent_uses_maximum_fit() -> None:
    gift = GiftEvidence(1, AT, "bonus_points", True, True, "sent", 0.7)
    result = apply(gift)
    assert result.state.components.gift_fit == 0.7
    assert apply(replace(gift, source_id=2, elasticity=0.4), result.state) == result
    assert apply(replace(gift, kind="personal_call")).state.components.gift_fit == 0
    for field in ("task_done", "issued"):
        assert apply(replace(gift, **{field: False})).state.components.gift_fit == 0


@pytest.mark.parametrize("value", [True, -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_numeric_inputs_rejected(value) -> None:
    with pytest.raises(ValueError):
        CareComponents(speed=value)
    with pytest.raises(ValueError):
        apply(communication(), weights=WEIGHTS | {"tone": value})


@pytest.mark.parametrize("source", [True, 0, -1, 1.5])
def test_invalid_source_ids_rejected(source) -> None:
    with pytest.raises(ValueError):
        communication(source_id=source)


def test_inconsistent_sticky_state_rejected() -> None:
    with pytest.raises(ValueError):
        CareState(CareComponents(tone=1.0), tone_violated=True)
    with pytest.raises(ValueError):
        CareState(CareComponents(sla=1.0), sla_breached=True)
    with pytest.raises(ValueError):
        communication(at=AT.replace(tzinfo=None))
    with pytest.raises(ValueError):
        apply(communication(), weights={"tone": 1.0})


@pytest.mark.parametrize("status", ["queued", "failed", "suppressed"])
def test_unsent_delivery_status_cannot_credit_message_or_gift(status) -> None:
    assert apply(communication(delivery_status=status)).state == EMPTY
    gift = GiftEvidence(1, AT, "bonus_points", True, True, status, 0.7)
    assert apply(gift).state == EMPTY


@pytest.mark.parametrize("status", [True, None, "sending", ""])
def test_unknown_delivery_status_is_rejected(status) -> None:
    with pytest.raises(ValueError):
        communication(delivery_status=status)
    with pytest.raises(ValueError):
        GiftEvidence(1, AT, "bonus_points", True, True, status, 0.7)
