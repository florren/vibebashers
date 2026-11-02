"""T-248: описательная статистика без внешних сервисов и бизнес-порогов.

Spearman для bucket probability описывает связь агрегированных корзин;
его n — число пригодных пар корзин, а не число посетителей.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from decimal import Decimal

Number = int | float | Decimal


def _finite(value: Number | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _ranks(values: list[float]) -> list[float]:
    # Средний ранг совпадающих значений; обычная формула 1-6Σd²/(n³-n)
    # без поправки на ties здесь неприменима.
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        rank = (start + 1 + end) / 2
        for index, _ in ordered[start:end]:
            result[index] = rank
        start = end
    return result


def spearman(pairs: Iterable[tuple[Number | None, Number | None]]) -> tuple[float | None, int]:
    """Pairwise complete finite values; при n<2 или постоянной величине rho unknown."""
    valid = []
    for x, y in pairs:
        a, b = _finite(x), _finite(y)
        if a is not None and b is not None:
            valid.append((a, b))
    n = len(valid)
    if n < 2:
        return None, n
    xs, ys = [x for x, _ in valid], [y for _, y in valid]
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None, n
    return statistics.correlation(_ranks(xs), _ranks(ys)), n


def quartiles(values: Iterable[Number | None]) -> tuple[int, tuple[float, float, float] | None]:
    """Линейная интерполяция (R7 / PostgreSQL percentile_cont), только известные значения."""
    valid = []
    for value in values:
        number = _finite(value)
        if number is not None:
            valid.append(number)
    if not valid:
        return 0, None
    if len(valid) == 1:
        return 1, (valid[0], valid[0], valid[0])
    q1, median, q3 = statistics.quantiles(valid, n=4, method="inclusive")
    return len(valid), (q1, median, q3)
