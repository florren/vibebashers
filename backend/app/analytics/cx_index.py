"""T-256: чистая формула демонстрационного индекса, ТЗ14.1; без денежных расчётов."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

COMPONENTS = ("negativity", "criticality", "sla", "churn")
DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType(dict(zip(COMPONENTS, (0.4, 0.25, 0.2, 0.15), strict=True)))


@dataclass(frozen=True)
class Observation:
    """Значение среди известных наблюдений; неполное покрытие не становится полным."""

    value: float | None
    known: int
    total: int

    def __post_init__(self) -> None:
        if type(self.known) is not int or type(self.total) is not int or not 0 <= self.known <= self.total:
            raise ValueError("known/total должны быть целыми: 0 <= known <= total")
        if self.value is not None:
            if isinstance(self.value, bool) or not math.isfinite(self.value) or not 0 <= self.value <= 100:
                raise ValueError("Компонент должен быть конечным числом 0…100 либо unknown")
            if self.known == 0 and self.total > 0:
                raise ValueError("Нет известных наблюдений для численного компонента")

    @property
    def complete_value(self) -> float | None:
        return self.value if self.known == self.total else None


def validated_weights(value: object) -> dict[str, float]:
    """Граница settings: четыре явных finite coefficients, без тихой нормировки."""
    if not isinstance(value, Mapping) or len(value) != len(COMPONENTS) or any(key not in value for key in COMPONENTS):
        raise ValueError("Нужны ровно четыре явных веса CX")
    result: dict[str, float] = {}
    for key in COMPONENTS:
        raw = value[key]
        if type(raw) not in (int, float):
            raise ValueError("Веса CX должны быть конечными неотрицательными числами")
        try:
            weight = float(raw)
        except OverflowError as exc:
            raise ValueError("Вес CX не представим конечным числом") from exc
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("Веса CX должны быть конечными неотрицательными числами")
        result[key] = weight
    if not any(result.values()):
        raise ValueError("Хотя бы один вес CX должен быть положительным")
    return result


def weighted_index(*, components: Mapping[str, Observation], weights: Mapping[str, float]) -> float | None:
    """CX=clamp(100−Σwᵢxᵢ); веса обязательны и никогда не перенормируются."""
    if set(components) != set(COMPONENTS):
        raise ValueError("Нужны ровно четыре компонента CX")
    weights = validated_weights(weights)
    values = {key: value.complete_value for key, value in components.items()}
    # Даже нулевой вес не позволяет скрыть unknown-компонент исходной модели.
    if any(value is None for value in values.values()):
        return None
    # Все слагаемые неотрицательны: насыщение каждого на100 эквивалентно
    # итоговому clamp и не допускает overflow суммы при больших явных весах.
    penalty = math.fsum(min(100.0, weights[key] * value) for key, value in values.items() if value is not None)
    return max(0.0, min(100.0, 100.0 - penalty))


def hourly_delta(*, current: float | None, previous: float | None) -> float | None:
    """Разница только двух сопоставимых наблюдённых индексов; unknown не равен нулю."""
    for value in (current, previous):
        if value is not None and (isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError("Индекс должен быть конечным числом 0…100 либо unknown")
    return current - previous if current is not None and previous is not None else None
