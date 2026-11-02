"""T-240: чистая помесячная история; никакой записи в пока не согласованную DDL.

Месяцы, пересекающие последние 14 дней, содержат ТОЛЬКО реальные сигналы этой
части baseline. В них не достраивается синтетический остаток месяца.
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.contracts.enums import Criticality, ProductLine
from app.sim.rng import SimRng

MSK = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class ActualSignal:
    run_id: int
    product_line: ProductLine | None
    at: dt.datetime
    source_platform: str | None
    criticality: Criticality | None
    negative: bool

    def __post_init__(self) -> None:
        if isinstance(self.run_id, bool) or not isinstance(self.run_id, int) or self.run_id <= 0:
            raise ValueError("run_id должен быть положительным int")
        if not isinstance(self.at, dt.datetime) or self.at.utcoffset() is None:
            raise ValueError("требуется aware timestamp")
        if self.product_line is not None and not isinstance(self.product_line, ProductLine):
            raise ValueError("неизвестный тип product_line")
        if self.criticality is not None and not isinstance(self.criticality, Criticality):
            raise ValueError("неизвестный тип criticality")
        if self.source_platform is not None and not isinstance(self.source_platform, str):
            raise ValueError("source_platform должен быть строкой или None")
        if not isinstance(self.negative, bool):
            raise ValueError("negative должен быть bool")


@dataclass(frozen=True)
class HistoryConfig:
    seasonality: tuple[float, ...]
    fault_spike_multiplier: float
    jitter_ratio: float

    def __post_init__(self) -> None:
        values = (*self.seasonality, self.fault_spike_multiplier, self.jitter_ratio)
        if len(self.seasonality) != 12 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in values
        ):
            raise ValueError("исторические коэффициенты должны быть конечными неотрицательными числами")
        if self.jitter_ratio > 1 or self.fault_spike_multiplier < 1:
            raise ValueError("некорректные jitter/spike коэффициенты")


@dataclass(frozen=True)
class HistoryRow:
    run_id: int
    product_line: ProductLine
    month: dt.date
    signal_count: int
    negative_count: int
    critical_count: int
    by_source: dict[str, dict[str, int]]
    is_synthetic: bool
    is_partial: bool
    coverage_start: dt.datetime
    coverage_end: dt.datetime
    loss_rub: Decimal | None


@dataclass(frozen=True)
class HistoryBuild:
    rows: tuple[HistoryRow, ...]
    unmapped_actual_count: int


def _month(value: dt.date, offset: int) -> dt.date:
    index = value.year * 12 + value.month - 1 + offset
    return dt.date(index // 12, index % 12 + 1, 1)


def _buckets(signals: list[ActualSignal], known_platforms: frozenset[str]) -> Counter[tuple[str, str]]:
    return Counter(
        (
            row.source_platform if row.source_platform in known_platforms else "unknown",
            row.criticality.value if row.criticality is not None else "unknown",
        )
        for row in signals
    )


def _distribute(total: int, weights: Counter[tuple[str, str]]) -> dict[str, dict[str, int]]:
    if not weights or not total:
        return {}
    denominator = sum(weights.values())
    base = {key: total * count // denominator for key, count in weights.items()}
    remainder = total - sum(base.values())
    order = sorted(weights, key=lambda key: (-(total * weights[key] % denominator), key))
    for key in order[:remainder]:
        base[key] += 1
    result: dict[str, dict[str, int]] = {}
    for (source, severity), count in sorted(base.items()):
        if count:
            result.setdefault(source, {})[severity] = count
    return result


def build_history(
    *,
    seed: int,
    run_id: int,
    anchor: dt.datetime,
    actual: list[ActualSignal],
    product_lines: frozenset[ProductLine],
    known_platforms: frozenset[str],
    fault_months: frozenset[tuple[ProductLine, dt.date]],
    config: HistoryConfig,
) -> HistoryBuild:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed должен быть int")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("требуется положительный run_id")
    if anchor.utcoffset() is None or ProductLine.OTHER in product_lines:
        raise ValueError("нужны aware anchor и физические направления")
    if any(row.run_id != run_id or row.at.utcoffset() is None for row in actual):
        raise ValueError("вход содержит foreign run или naive timestamp")
    now = anchor.astimezone(MSK)
    tail_start = now - dt.timedelta(days=14)
    tail = [row for row in actual if tail_start <= row.at < now]
    unmapped = sum(row.product_line not in product_lines for row in tail)
    rng = SimRng(seed)
    rows = []
    for line in sorted(product_lines):
        observed = [row for row in tail if row.product_line == line]
        counts = _buckets(observed, known_platforms)
        for offset in range(-11, 1):
            month = _month(now.date(), offset)
            start = dt.datetime.combine(month, dt.time(), MSK)
            finish = dt.datetime.combine(_month(month, 1), dt.time(), MSK)
            real = finish > tail_start and start < now
            if real:
                selected = [row for row in observed if start <= row.at.astimezone(MSK) < finish]
                total = len(selected)
                by_source = _distribute(total, _buckets(selected, known_platforms))
                negative = sum(row.negative for row in selected)
                critical = sum(row.criticality == Criticality.HIGH for row in selected)
                coverage_start, coverage_end = max(start, tail_start), min(finish, now)
            else:
                # Только агрегатная синтетика, а не утверждение о реальном fault/incident.
                factor = config.seasonality[month.month - 1]
                if (line, month) in fault_months:
                    factor *= config.fault_spike_multiplier
                factor *= 1 + rng.uniform(-config.jitter_ratio, config.jitter_ratio)
                total = round(len(observed) / 14 * calendar.monthrange(month.year, month.month)[1] * factor)
                by_source = _distribute(total, counts)
                negative = round(total * sum(row.negative for row in observed) / len(observed)) if observed else 0
                critical = sum(parts.get("high", 0) for parts in by_source.values())
                coverage_start, coverage_end = start, finish
            rows.append(
                HistoryRow(
                    run_id,
                    line,
                    month,
                    total,
                    negative,
                    critical,
                    by_source,
                    not real,
                    coverage_start != start or coverage_end != finish,
                    coverage_start,
                    coverage_end,
                    None,
                )
            )
    return HistoryBuild(tuple(rows), unmapped)
