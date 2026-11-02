"""T-161: явное состояние шести care-компонентов по утверждённой demo-policy.

Чистое ядро не читает БД, не подтверждает принадлежность источника эпизоду и не
делает commit. Durable writer обязан проверить run/client/cause и receipt до
вызова, затем сохранить ВСЁ CareState вместе с результатом в своей транзакции.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Literal

DeliveryStatus = Literal["queued", "sent", "delivered", "failed", "suppressed"]
_DELIVERY_STATUSES = frozenset({"queued", "sent", "delivered", "failed", "suppressed"})

COMPONENTS = frozenset({"proactive", "speed", "sla", "gift_fit", "tone", "explanation"})


def _unit(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("компонент должен быть конечным числом [0,1]")


def _source(source_id: int, at: dt.datetime) -> None:
    if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0:
        raise ValueError("source_id должен быть положительным int")
    if not isinstance(at, dt.datetime) or at.utcoffset() is None:
        raise ValueError("требуется aware время evidence")


@dataclass(frozen=True)
class CareComponents:
    proactive: float = 0.0
    speed: float = 0.0
    sla: float = 0.0
    gift_fit: float = 0.0
    tone: float = 0.0
    explanation: float = 0.0

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            _unit(value)


@dataclass(frozen=True)
class CareState:
    components: CareComponents
    first_reply_at: dt.datetime | None = None
    tone_violated: bool = False
    sla_breached: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.components, CareComponents):
            raise ValueError("требуется типизированный CareComponents")
        if self.first_reply_at is not None:
            _source(1, self.first_reply_at)
        if not isinstance(self.tone_violated, bool) or not isinstance(self.sla_breached, bool):
            raise ValueError("sticky flags должны быть bool")
        if (self.tone_violated and self.components.tone != 0) or (self.sla_breached and self.components.sla != 0):
            raise ValueError("sticky нарушение не может иметь положительный компонент")


@dataclass(frozen=True)
class CareContext:
    episode_started_at: dt.datetime
    first_complaint_at: dt.datetime | None
    first_response_minutes: float

    def __post_init__(self) -> None:
        _source(1, self.episode_started_at)
        if self.first_complaint_at is not None:
            _source(1, self.first_complaint_at)
            if self.first_complaint_at < self.episode_started_at:
                raise ValueError("жалоба не может предшествовать эпизоду")
        value = self.first_response_minutes
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("явный срок первого ответа должен быть положительным")


@dataclass(frozen=True)
class CarePolicy:
    explanation_scores: Mapping[str, float]
    first_reply_excluded_templates: frozenset[str]

    def __post_init__(self) -> None:
        if not self.explanation_scores or not all(isinstance(key, str) and key for key in self.explanation_scores):
            raise ValueError("нужен явный catalog explanation")
        for score in self.explanation_scores.values():
            _unit(score)
        if not isinstance(self.first_reply_excluded_templates, frozenset) or not all(
            isinstance(x, str) for x in self.first_reply_excluded_templates
        ):
            raise ValueError("нужен явный набор исключённых шаблонов")
        object.__setattr__(self, "explanation_scores", MappingProxyType(dict(self.explanation_scores)))


@dataclass(frozen=True)
class CommunicationEvidence:
    source_id: int
    at: dt.datetime
    delivery_status: DeliveryStatus
    customer_attributed: bool
    valid: bool
    proactive: bool
    template_code: str
    template_fields_present: bool

    def __post_init__(self) -> None:
        _source(self.source_id, self.at)
        for value in (
            self.customer_attributed,
            self.valid,
            self.proactive,
            self.template_fields_present,
        ):
            if not isinstance(value, bool):
                raise ValueError("communication predicates должны быть bool")
        if self.delivery_status not in _DELIVERY_STATUSES:
            raise ValueError("неизвестный статус customer notification")
        if not isinstance(self.template_code, str):
            raise ValueError("template_code должен быть строкой")


@dataclass(frozen=True)
class SlaEvidence:
    source_id: int
    at: dt.datetime
    deadline_known: bool
    breached: bool

    def __post_init__(self) -> None:
        _source(self.source_id, self.at)
        if not isinstance(self.deadline_known, bool) or not isinstance(self.breached, bool):
            raise ValueError("SLA predicates должны быть bool")


@dataclass(frozen=True)
class GiftEvidence:
    source_id: int
    at: dt.datetime
    kind: Literal["bonus_points", "partner_privilege", "personal_call"]
    task_done: bool
    issued: bool
    offer_status: DeliveryStatus
    elasticity: float

    def __post_init__(self) -> None:
        _source(self.source_id, self.at)
        if self.kind not in ("bonus_points", "partner_privilege", "personal_call"):
            raise ValueError("неизвестный вид подарка")
        for value in (self.task_done, self.issued):
            if not isinstance(value, bool):
                raise ValueError("gift predicates должны быть bool")
        if self.offer_status not in _DELIVERY_STATUSES:
            raise ValueError("неизвестный статус gift offer")
        _unit(self.elasticity)


CareObservation = CommunicationEvidence | SlaEvidence | GiftEvidence


@dataclass(frozen=True)
class CareResult:
    state: CareState
    score: Decimal


def evaluate_care(
    previous: CareState,
    evidence: CareObservation,
    *,
    context: CareContext,
    policy: CarePolicy,
    weights: Mapping[str, float],
) -> CareResult:
    """Дубликат не накапливает reward; receipt и принадлежность проверяются владельцем."""
    if set(weights) != COMPONENTS:
        raise ValueError("требуются ровно шесть catalog weights")
    for value in weights.values():
        _unit(value)
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("catalog weights должны давать сумму 1 без повторной нормализации")
    if not isinstance(evidence, (CommunicationEvidence, SlaEvidence, GiftEvidence)):
        raise ValueError("неизвестный тип evidence")
    if evidence.at < context.episode_started_at:
        return CareResult(previous, _score(previous.components, weights))
    state, values = previous, previous.components
    if (
        isinstance(evidence, CommunicationEvidence)
        and evidence.delivery_status in ("sent", "delivered")
        and evidence.customer_attributed
    ):
        if not evidence.valid:
            values = replace(values, tone=0.0)
            state = replace(state, tone_violated=True, components=values)
        else:
            values = replace(values, tone=0.0 if state.tone_violated else 1.0)
            if evidence.proactive and (context.first_complaint_at is None or evidence.at < context.first_complaint_at):
                values = replace(values, proactive=1.0)
            if evidence.template_fields_present:
                values = replace(
                    values,
                    explanation=max(values.explanation, policy.explanation_scores.get(evidence.template_code, 0.0)),
                )
            if (
                context.first_complaint_at is not None
                and evidence.at >= context.first_complaint_at
                and evidence.template_code not in policy.first_reply_excluded_templates
            ):
                first = min(state.first_reply_at, evidence.at) if state.first_reply_at else evidence.at
                delay = (first - context.first_complaint_at).total_seconds() / 60
                speed = (
                    1.0
                    if delay <= context.first_response_minutes
                    else max(0.0, 2 - delay / context.first_response_minutes)
                )
                state = replace(state, first_reply_at=first)
                values = replace(values, speed=speed)
    elif isinstance(evidence, SlaEvidence):
        breach = state.sla_breached or evidence.breached
        values = replace(values, sla=1.0 if evidence.deadline_known and not breach else 0.0)
        state = replace(state, sla_breached=breach, components=values)
    elif (
        isinstance(evidence, GiftEvidence)
        and evidence.task_done
        and evidence.issued
        and evidence.offer_status in ("sent", "delivered")
        and evidence.kind != "personal_call"
    ):
        values = replace(values, gift_fit=max(values.gift_fit, evidence.elasticity))
    state = replace(state, components=values)
    return CareResult(state, _score(values, weights))


def _score(components: CareComponents, weights: Mapping[str, float]) -> Decimal:
    return sum(
        (Decimal(str(weights[key])) * Decimal(str(value)) for key, value in asdict(components).items()), Decimal(0)
    ).quantize(Decimal(".001"), rounding=ROUND_HALF_UP)
