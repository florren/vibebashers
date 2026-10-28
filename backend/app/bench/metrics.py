"""Сводные метрики прогона бенчмарка (OpenAPI BenchRun.metrics, ТЗ §14.2)."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any


def _accuracy(results: list[dict[str, Any]], key: str) -> float | None:
    vals = [
        bool(r["correct"].get(key)) for r in results if key in (r.get("gold") or {}) and key in r.get("correct", {})
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _stability(results: list[dict[str, Any]], repeats: int) -> float | None:
    if repeats <= 1:
        return None
    by_case: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_case[int(r["case_id"])].append(r)
    stable = 0
    total = 0
    for rows in by_case.values():
        if len(rows) < 2:
            continue
        total += 1
        types = {row["predicted"].get("signal_type") for row in rows}
        products = {row["predicted"].get("product") for row in rows}
        systems = {row["predicted"].get("system") for row in rows}
        if len(types) == len(products) == len(systems) == 1:
            stable += 1
    if total == 0:
        return None
    return stable / total


def aggregate(results: list[dict[str, Any]], *, repeats: int = 1) -> dict[str, Any]:
    """Агрегирует строки bench_results (+ gold на каждой строке) в словарь метрик BenchRun."""
    if not results:
        return {
            "json_valid_rate": 0.0,
            "tool_success_rate": 0.0,
            "retries_avg": 0.0,
            "fallback_rate": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "tokens_total": 0,
            "cost_estimate": 0.0,
            "stability": _stability(results, repeats),
        }

    latencies = [int(r["latency_ms"]) for r in results]
    json_valid = [bool(r.get("json_valid_first_try")) for r in results]
    tool_ok = [
        bool(r.get("tool_ok", bool(r.get("predicted")) and isinstance(r.get("predicted"), dict))) for r in results
    ]
    retries = [int(r.get("retries") or 0) for r in results]
    fallbacks = [bool(r.get("fallback_mock")) for r in results]
    tokens = sum(int(r.get("prompt_tokens") or 0) + int(r.get("completion_tokens") or 0) for r in results)
    cost = sum(float(r.get("cost_rub") or 0.0) for r in results)

    metrics: dict[str, Any] = {
        "json_valid_rate": sum(json_valid) / len(json_valid),
        "tool_success_rate": sum(tool_ok) / len(tool_ok),
        "retries_avg": mean(retries),
        "fallback_rate": sum(fallbacks) / len(fallbacks),
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "tokens_total": tokens,
        "cost_estimate": round(cost, 6),
        "stability": _stability(results, repeats),
    }

    for field, gold_key in (
        ("accuracy_type", "signal_type"),
        ("accuracy_product", "product"),
        ("accuracy_system", "system"),
        ("accuracy_criticality", "criticality"),
        ("accuracy_route", "team"),
    ):
        acc = _accuracy(results, gold_key if gold_key != "team" else "team")
        if acc is not None:
            metrics[field] = acc

    high_gold = [r for r in results if (r.get("gold") or {}).get("criticality") == "high"]
    if high_gold:
        recalled = sum(1 for r in high_gold if (r.get("predicted") or {}).get("criticality") == "high")
        metrics["recall_critical"] = recalled / len(high_gold)

    return metrics
