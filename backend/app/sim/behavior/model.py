"""Чистые решения ТЗ 4.5 без БД, таймеров процесса и неявных policy defaults.

Вызывающая транзакция обязана атомарно сохранить результат и SimRng.dump_state().
Повторная доставка evidence должна отсеиваться durable receipt ДО вызова ядра.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal, Protocol

from app.contracts.enums import ClientState
from app.contracts.events.behavior.psychotype_params import PsychotypeParams
from app.sim.rng import SimRng

CareKind = Literal["agent_reply", "proactive_notice", "progress_update", "gift", "sla_breach", "tone_violation"]


def _unit(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite and within [0,1]")


@dataclass(frozen=True)
class CareEvidence:
    kind: CareKind
    source_id: int
    at: dt.datetime

    def __post_init__(self) -> None:
        if self.source_id <= 0 or self.at.utcoffset() is None:
            raise ValueError("care evidence requires positive source_id and aware timestamp")


class CareStrategy(Protocol):
    """ADR-reviewed scoring; weights alone do not define component observations."""

    def __call__(self, previous: float, evidence: CareEvidence, weights: Mapping[str, float]) -> float: ...


@dataclass(frozen=True)
class BehaviorPolicy:
    segment_multiplier: float
    retained_threshold: float
    care_strategy: CareStrategy

    def __post_init__(self) -> None:
        if not math.isfinite(self.segment_multiplier) or self.segment_multiplier < 0:
            raise ValueError("segment_multiplier must be finite and nonnegative")
        _unit("retained_threshold", self.retained_threshold)
        if not callable(self.care_strategy):
            raise ValueError("care_strategy is required")


@dataclass(frozen=True)
class Snapshot:
    state: ClientState
    care_score: float
    repeat_count: int
    sla_breached: bool

    def __post_init__(self) -> None:
        _unit("care_score", self.care_score)
        if self.repeat_count < 0:
            raise ValueError("repeat_count must be nonnegative")


@dataclass(frozen=True)
class Transition:
    before: Snapshot
    after: Snapshot
    trigger: str


@dataclass(frozen=True)
class ComplaintDecision:
    transition: Transition
    complain_due: dt.datetime | None
    silent_decline: bool


@dataclass(frozen=True)
class HazardDecision:
    transition: Transition
    raw_hazard: float
    closure_requested: bool


def hazard(params: PsychotypeParams, policy: BehaviorPolicy, snapshot: Snapshot, *, repeat: float) -> float:
    """Точная формула ТЗ 4.5. Raw hazard не обрезается под контракт [0,1]."""
    if not math.isfinite(repeat) or repeat < 0:
        raise ValueError("repeat must be explicit, finite and nonnegative")
    return (
        params.base_churn_hazard
        * policy.segment_multiplier
        * (1 + 0.5 * repeat)
        * (1 + 0.8 * snapshot.sla_breached)
        * (1 - params.care_sensitivity * snapshot.care_score)
    )


class BehaviorModel:
    def __init__(self, params: PsychotypeParams, policy: BehaviorPolicy) -> None:
        params = PsychotypeParams.model_validate(params.model_dump())
        if params.care_weights is None:
            raise ValueError("care_weights are required; no fallback policy")
        self.weights: Mapping[str, float] = {
            k: float(v) for k, v in params.care_weights.model_dump(exclude_none=True).items()
        }
        if not self.weights or any(not math.isfinite(v) or v < 0 for v in self.weights.values()):
            raise ValueError("care_weights must be finite and nonnegative")
        if not math.isclose(sum(self.weights.values()), 1, abs_tol=1e-9):
            raise ValueError("care_weights must sum to 1")
        lo, hi = (item.root for item in params.complain_delay_min)
        if lo > hi:
            raise ValueError("complain_delay_min is reversed")
        self.weights = MappingProxyType(self.weights)
        self.params, self.policy = params, policy

    def affected(self, previous: Snapshot, at: dt.datetime, rng: SimRng) -> ComplaintDecision:
        if at.utcoffset() is None:
            raise ValueError("aware timestamp required")
        if previous.state not in (ClientState.CALM, ClientState.SATISFIED, ClientState.RETAINED):
            raise ValueError("affected episode must be deduplicated before model invocation")
        current = replace(previous, state=ClientState.AFFECTED)
        due = None
        silent = False
        if rng.random() < self.params.p_complain:
            lo, hi = (item.root for item in self.params.complain_delay_min)
            due = at + dt.timedelta(minutes=rng.randint(lo, hi))
        else:
            silent = rng.random() < self.params.silent_decline_prob
        return ComplaintDecision(Transition(previous, current, "fault"), due, silent)

    def complaint_due(self, previous: Snapshot) -> Transition:
        self._require(previous, (ClientState.AFFECTED,))
        return Transition(previous, replace(previous, state=ClientState.COMPLAINING), "timer")

    def signal_sent(self, previous: Snapshot) -> Transition:
        self._require(previous, (ClientState.COMPLAINING, ClientState.ASKS_AGAIN, ClientState.ESCALATES))
        return Transition(previous, replace(previous, state=ClientState.WAITING), "signal_sent")

    def observe_care(self, previous: Snapshot, evidence: CareEvidence) -> Transition:
        if previous.state == ClientState.CHURNED:
            raise ValueError("care cannot modify a closed account")
        score = self.policy.care_strategy(previous.care_score, evidence, self.weights)
        _unit("care_strategy result", score)
        current = replace(
            previous, care_score=score, sla_breached=previous.sla_breached or evidence.kind == "sla_breach"
        )
        return Transition(previous, current, evidence.kind)

    def repeat(self, previous: Snapshot, rng: SimRng) -> Transition:
        self._require(previous, (ClientState.WAITING,))
        if rng.random() >= self.params.repeat_prob:
            return Transition(previous, previous, "timer")
        state = ClientState.ESCALATES if rng.random() < self.params.escalation_prob else ClientState.ASKS_AGAIN
        return Transition(previous, replace(previous, state=state, repeat_count=previous.repeat_count + 1), "timer")

    def sla_tick(self, previous: Snapshot, rng: SimRng, *, repeat: float) -> HazardDecision:
        self._require(previous, (ClientState.WAITING, ClientState.CHURN_INTENT))
        value = hazard(self.params, self.policy, previous, repeat=repeat)
        # Бернулли при hazard >= 1 достоверно срабатывает; исходная величина остаётся явной.
        selected = rng.random() < value
        current = replace(previous, state=ClientState.CHURN_INTENT) if selected else previous
        return HazardDecision(
            Transition(previous, current, "timer"), value, selected and previous.state == ClientState.CHURN_INTENT
        )

    def closure(self, previous: Snapshot) -> Transition | None:
        """Закрытие проблемы, не счёта. Исход ниже порога пока не определён policy."""
        if previous.state in (ClientState.CALM, ClientState.CHURNED):
            raise ValueError("no active problem to close")
        if previous.care_score < self.policy.retained_threshold:
            return None
        return Transition(previous, replace(previous, state=ClientState.RETAINED), "closure")

    @staticmethod
    def _require(snapshot: Snapshot, allowed: tuple[ClientState, ...]) -> None:
        if snapshot.state not in allowed:
            raise ValueError(f"invalid source state: {snapshot.state}")
