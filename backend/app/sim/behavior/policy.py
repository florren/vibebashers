"""Утверждённый пакет demo-policy: явные значения, pinning и domain preflight.

Загрузка сама ничего не активирует. validation_only нужен для scratch proposal;
runtime получит этот объект только после завершённого wiring и actual schema chain.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.contracts.events.behavior.psychotype_params import PsychotypeParams
from app.contracts.registry import validate
from app.sim.behavior.care import COMPONENTS, CarePolicy


@dataclass(frozen=True)
class DemoPolicy:
    sha256: str
    _snapshot_json: str
    source_sha256: str

    @property
    def spec(self) -> dict[str, Any]:
        # Внешний caller не может менять закреплённый пакет через dict alias.
        return dict(json.loads(self._snapshot_json))

    @classmethod
    def load(cls, path: Path, *, validation_only: bool) -> DemoPolicy:
        raw = path.read_bytes()
        if len(raw) > 65536:
            raise ValueError("behavior policy превышает ограничение размера")
        spec = yaml.safe_load(raw)
        if (
            not isinstance(spec, dict)
            or spec.get("status") != "approved_for_implementation"
            or spec.get("approved_by") != "user_in_chat"
        ):
            raise ValueError("нужен утверждённый пакет behavior policy")
        if not isinstance(spec.get("enabled"), bool):
            raise ValueError("enabled должен быть явным bool")
        if spec.get("enabled") is not True and not validation_only:
            raise ValueError("behavior runtime ещё выключен")
        if type(spec.get("version")) is not int or spec["version"] != 1:
            raise ValueError("неподдерживаемая версия behavior policy")
        segments = spec.get("segment_multiplier")
        if not isinstance(segments, dict) or not segments:
            raise ValueError("нужны явные segment multipliers")
        for value in segments.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("некорректный segment multiplier")
        threshold = spec.get("retained_threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("нужен retained threshold [0,1]")
        if (
            spec["hazard"]["cadence_sim_minutes"] != 15
            or spec["hazard"]["repeat_meaning"] != "boolean_at_least_one_actual_repeat_complaint"
        ):
            raise ValueError("неподдерживаемая семантика hazard")
        snapshot = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(hashlib.sha256(snapshot.encode()).hexdigest(), snapshot, hashlib.sha256(raw).hexdigest())

    @property
    def care(self) -> CarePolicy:
        return CarePolicy(
            self.spec["care"]["components"]["explanation"]["eligible_template_score"],
            frozenset(self.spec["care"]["first_reply_excluded_templates"]),
        )

    def multiplier(self, segment: str) -> float:
        if segment not in self.spec["segment_multiplier"]:
            raise ValueError("segment отсутствует в утверждённой policy")
        return float(self.spec["segment_multiplier"][segment])

    def preflight(self, parameters: Mapping[str, dict[str, Any]], segments: set[str]) -> None:
        if segments != set(self.spec["segment_multiplier"]):
            raise ValueError("policy должна явно описывать все текущие сегменты")
        for value in parameters.values():
            if validate(value, "behavior/psychotype_params"):
                raise ValueError("psychotype parameters нарушают числовой контракт")
            params = PsychotypeParams.model_validate(value)
            if params.care_weights is None:
                raise ValueError("care_weights обязательны")
            weights = params.care_weights.model_dump(exclude_none=True)
            if set(weights) != COMPONENTS or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
                raise ValueError("care_weights не дают сумму 1")
            if params.privilege_elasticity is None:
                raise ValueError("privilege_elasticity обязательна для утверждённой gift strategy")
            inbound = set(self.spec["complaint"]["eligible_inbound_channels"])
            if sum(value.root for key, value in params.channel_weights.items() if key in inbound) <= 0:
                raise ValueError("нет разрешённого входящего канала complaint")
            for segment in segments:
                # Максимум формулы: care=0, repeat=true, SLA breach=true.
                raw = params.base_churn_hazard * self.multiplier(segment) * 1.5 * 1.8
                if not math.isfinite(raw) or not 0 <= raw <= 1:
                    raise ValueError("raw hazard вне [0,1]; нельзя clamp или сериализовать в event")
