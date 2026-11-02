"""Движок бизнес-правил (узел check_rules, ДТЗ): DSL condition из business_rules → matched/not_matched/error + rule_evaluations.

Поддерживаемые предикаты: {field, eq|ne|gt|gte|lt|lte|in}, {all: [...]}, {any: [...]}, {not: {...}}.
Специальные ({duplicate_within_s}, {within_promo}) считаются не сработавшими — они требуют данных Mock-АБС (карточки T-15x)."""

from __future__ import annotations

import time
from typing import Any

import psycopg

from app.sim.events import dumps


def _get(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _cmp(a: Any, op: str, b: Any) -> bool:
    if op == "eq":
        return bool(a == b) or (isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b))
    if op == "ne":
        return bool(a != b)
    if op == "in":
        return a in (b or [])
    if a is None or b is None:
        return False
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return {"gt": fa > fb, "gte": fa >= fb, "lt": fa < fb, "lte": fa <= fb}[op]


def evaluate(cond: dict[str, Any], ctx: dict[str, Any]) -> bool:
    if "all" in cond:
        return all(evaluate(c, ctx) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, ctx) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], ctx)
    if "field" in cond:
        val = _get(ctx, cond["field"])
        for op in ("eq", "ne", "gt", "gte", "lt", "lte", "in"):
            if op in cond:
                ref = cond[op]
                if (
                    isinstance(ref, str) and "." in ref and _get(ctx, ref) is not None
                ):  # ссылка на другое поле (promo.rate)
                    ref = _get(ctx, ref)
                return _cmp(val, op, ref)
        return False  # within_promo и прочие расширения — пока не поддержаны
    return False


async def check_rules(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    signal_id: int,
    agent_run_id: int,
    operations: list[dict[str, Any]],
    refund_operations: dict[str, list[dict[str, Any]]] | None = None,
    tariff_fee_pct: float = 0.0,
) -> list[dict[str, Any]]:
    """Прогоняет активные правила по операциям клиента из контекста; пишет rule_evaluations; возвращает сработавшие."""
    cur = await conn.execute(
        "select code, condition, action, limits, owner_team_code, error_code, version from business_rules where is_active order by code"
    )
    rules = await cur.fetchall()
    matched: list[dict[str, Any]] = []
    for code, cond, action, limits, team, error_code, version in rules:
        t0 = time.perf_counter()
        hits: list[dict[str, Any]] = []
        result = "not_matched"
        try:
            candidates = (
                refund_operations.get(code, [])
                if action == "refund_fee" and refund_operations is not None
                else operations
            )
            for op in candidates:
                ctx = {
                    "operation": op,
                    "tariff": {"fee_pct": tariff_fee_pct},
                    "ledger": {"kind": "debit" if (op.get("amount_rub") or 0) > 0 else None},
                }
                if evaluate(cond, ctx):
                    hits.append(op)
            if hits:
                result = "matched"
        except Exception:  # noqa: BLE001 — ошибка правила не должна ронять агента
            result = "error"
        amount = float(sum(h.get("fee_amount") or 0 for h in hits)) if action == "refund_fee" else None
        evidence = {
            "operation_ids": [h.get("operation_id") for h in hits],
            "amount_rub": amount,
            "error_code": error_code,
        }
        await conn.execute(
            "insert into rule_evaluations (run_id, signal_id, agent_run_id, rule_code, rule_version, result, evidence, proposed_action, amount_rub, latency_ms) values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
            (
                run_id,
                signal_id,
                agent_run_id,
                code,
                version,
                result,
                dumps(evidence),
                action if result == "matched" else None,
                amount,
                int((time.perf_counter() - t0) * 1000),
            ),
        )
        if result == "matched":
            max_amount = float((limits or {}).get("max_amount_rub") or 0)
            matched.append(
                {
                    "rule_code": code,
                    "action": action,
                    "team": team,
                    "error_code": error_code,
                    "amount_rub": amount,
                    "operation_ids": evidence["operation_ids"],
                    "within_limit": amount is None or max_amount == 0 or amount <= max_amount,
                    "limits": limits or {},
                }
            )
    return matched
