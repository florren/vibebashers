"""Версионированные native факты отмены таймера; без вероятностей и текста клиента."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

MAX_DETAILS_BYTES = 2048
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
_KEYS = {
    "version",
    "episode_no",
    "work_kind",
    "due_sim",
    "cancellation_sim",
    "cancellation_observed_sim",
    "first_complaint_sim_at_cancellation",
    "complaint_observation_complete",
    "evidence_id",
    "evidence_kind",
    "evidence_source_id",
    "canonical_signal_id",
    "resolution_sim",
}


def _positive(value: Any, name: str, maximum: int = 9223372036854775807) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError(f"{name}: нужен положительный integer без bool")
    return value


def _aware(value: Any, name: str) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.utcoffset() is None:
        raise ValueError(f"{name}: нужен aware timestamp")
    return value


def _parse(value: Any, name: str, *, nullable: bool = False) -> dt.datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError(f"{name}: нужен native ISO timestamp с timezone")
    try:
        return _aware(dt.datetime.fromisoformat(value), name)
    except ValueError as exc:
        raise ValueError(f"{name}: некорректное время") from exc


@dataclass(frozen=True)
class CancellationDetails:
    episode_no: int
    work_kind: Literal["complaint", "repeat", "patience"]
    due_sim: dt.datetime
    cancellation_sim: dt.datetime
    cancellation_observed_sim: dt.datetime
    first_complaint_sim_at_cancellation: dt.datetime | None
    complaint_observation_complete: bool
    evidence_id: int
    evidence_kind: Literal["resolution", "agent_state"]
    evidence_source_id: int
    canonical_signal_id: int | None
    resolution_sim: dt.datetime | None

    def __post_init__(self) -> None:
        _positive(self.episode_no, "episode_no", 2147483647)
        _positive(self.evidence_id, "evidence_id")
        _positive(self.evidence_source_id, "evidence_source_id")
        if self.canonical_signal_id is not None:
            _positive(self.canonical_signal_id, "canonical_signal_id")
        if self.work_kind not in ("complaint", "repeat", "patience") or self.evidence_kind not in (
            "resolution",
            "agent_state",
        ):
            raise ValueError("неизвестный native kind")
        if type(self.complaint_observation_complete) is not bool:
            raise ValueError("complaint_observation_complete требует явный bool")
        _aware(self.due_sim, "due_sim")
        _aware(self.cancellation_sim, "cancellation_sim")
        _aware(self.cancellation_observed_sim, "cancellation_observed_sim")
        if self.cancellation_observed_sim < self.cancellation_sim:
            raise ValueError("observation не может предшествовать logical cancellation")
        for name in ("first_complaint_sim_at_cancellation", "resolution_sim"):
            value = getattr(self, name)
            if value is not None and _aware(value, name) > self.cancellation_sim:
                raise ValueError(f"{name} не может быть из будущего относительно cancellation")
        if self.evidence_kind == "agent_state" and (
            self.work_kind != "complaint"
            or self.canonical_signal_id is None
            or self.first_complaint_sim_at_cancellation is None
            or self.resolution_sim is not None
        ):
            raise ValueError("already_complained требует фактическую canonical complaint, без resolution credit")

    @property
    def action(self) -> Literal["cancelled_by_resolution", "already_complained"]:
        return "cancelled_by_resolution" if self.evidence_kind == "resolution" else "already_complained"

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"version": 1}
        for name in sorted(_KEYS - {"version"}):
            value = getattr(self, name)
            result[name] = value.isoformat() if isinstance(value, dt.datetime) else value
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_DETAILS_BYTES:
            raise ValueError("cancellation details превышает предел2048bytes")
        return result

    @classmethod
    def from_json(cls, value: Any) -> CancellationDetails:
        if not isinstance(value, dict) or set(value) != _KEYS:
            raise ValueError("cancellation details: требуется точная versioned структура")
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("неподдерживаемая версия cancellation details")
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_DETAILS_BYTES:
            raise ValueError("cancellation details превышает предел2048bytes")
        parsed = dict(value)
        parsed.pop("version")
        for name in ("due_sim", "cancellation_sim", "cancellation_observed_sim"):
            parsed[name] = _parse(parsed[name], name)
        for name in ("first_complaint_sim_at_cancellation", "resolution_sim"):
            parsed[name] = _parse(parsed[name], name, nullable=True)
        return cls(**parsed)
