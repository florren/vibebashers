"""Роутер тега `rules` (T-172): бизнес-правила (ТЗ 9.6) — список, полная замена с версионированием, отладочная проверка, история срабатываний."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api._compliance_support import run_context
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.rules.engine import evaluate
from app.sim.events import dumps

router = APIRouter(tags=["rules"])

RULE_COLS = (
    "code, name_ru, name_en, condition, action, limits, owner_team_code, error_code, is_active, version, updated_at"
)


class BusinessRuleIn(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    name_ru: str
    name_en: str | None = None
    condition: dict[str, Any]
    action: str
    limits: dict[str, Any] = Field(default_factory=dict)
    owner_team_code: str | None = None
    error_code: str | None = None
    is_active: bool = True
    version: int | None = None


@router.get("/api/rules", summary="Список бизнес-правил")
async def get_rules() -> Any:
    async with db() as conn:
        rows = await fetch_all(conn, f"select {RULE_COLS} from business_rules order by code")
    return JSONResponse(jsonable_encoder(rows))


@router.put(
    "/api/rules",
    summary="Полная замена набора правил (экран /settings → Правила); версия каждого изменённого правила увеличивается",
)
async def put_rules(body: list[BusinessRuleIn]) -> Any:
    """Отсутствующие в наборе правила деактивируются (история срабатываний сохраняется); изменённые получают version+1."""
    codes = [r.code for r in body]
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=422, detail="коды правил должны быть уникальны")
    for r in body:
        try:
            evaluate(r.condition, {"operation": {}, "tariff": {}, "ledger": {}})
        except Exception as exc:  # noqa: BLE001 — показываем автору правила, что условие не вычисляется
            raise HTTPException(status_code=422, detail=f"правило {r.code}: условие не вычисляется ({exc})") from exc
    changed = 0
    async with db() as conn:
        existing = {r["code"]: r for r in await fetch_all(conn, f"select {RULE_COLS} from business_rules")}
        for r in body:
            cur = existing.get(r.code)
            same = cur is not None and all(
                cur[k] == v
                for k, v in {
                    "name_ru": r.name_ru,
                    "condition": r.condition,
                    "action": r.action,
                    "limits": r.limits,
                    "owner_team_code": r.owner_team_code,
                    "error_code": r.error_code,
                    "is_active": r.is_active,
                }.items()
            )
            if same:
                continue
            changed += 1
            await conn.execute(
                """
                insert into business_rules (code, name_ru, name_en, condition, action, limits, owner_team_code, error_code, is_active, version, updated_at)
                values (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, 1, now())
                on conflict (code) do update set name_ru = excluded.name_ru, name_en = excluded.name_en, condition = excluded.condition,
                  action = excluded.action, limits = excluded.limits, owner_team_code = excluded.owner_team_code, error_code = excluded.error_code,
                  is_active = excluded.is_active, version = business_rules.version + 1, updated_at = now()
                """,
                (
                    r.code,
                    r.name_ru,
                    r.name_en,
                    dumps(r.condition),
                    r.action,
                    dumps(r.limits),
                    r.owner_team_code,
                    r.error_code,
                    r.is_active,
                ),
            )
        gone = [c for c in existing if c not in codes and existing[c]["is_active"]]
        if gone:
            await conn.execute(
                "update business_rules set is_active = false, version = version + 1, updated_at = now() where code = any(%s)",
                (gone,),
            )
        rows = await fetch_all(conn, f"select {RULE_COLS} from business_rules order by code")
    return JSONResponse(jsonable_encoder({"changed": changed, "deactivated": gone, "rules": rows}))


class EvaluateBody(BaseModel):
    operation_id: int | None = None
    client_id: int | None = None
    window_hours: int = 72


@router.post("/api/rules/evaluate", summary="Проверить правила для операции/клиента (отладка, панель Log)")
async def post_rules_evaluate(request: Request, body: EvaluateBody) -> Any:
    """Прогон активных правил без записи в rule_evaluations; ответ в формате события agent/rule_violation."""
    if body.operation_id is None and body.client_id is None:
        raise HTTPException(status_code=422, detail="нужен operation_id или client_id")
    async with db() as conn:
        run_id, sim_time = await run_context(request, conn)
        if body.operation_id is not None:
            ops = await fetch_all(
                conn,
                "select id, client_id, product_code, op_type, method, amount_rub::float as amount_rub, fee_amount::float as fee_amount, status, error_code, started_sim, merchant from operations where id = %s",
                (body.operation_id,),
            )
        else:
            ops = await fetch_all(
                conn,
                "select id, client_id, product_code, op_type, method, amount_rub::float as amount_rub, fee_amount::float as fee_amount, status, error_code, started_sim, merchant "
                "from operations where client_id = %s and started_sim >= %s order by started_sim desc limit 50",
                (body.client_id, sim_time - dt.timedelta(hours=body.window_hours)),
            )
        rules = await fetch_all(
            conn,
            "select code, condition, action, limits, owner_team_code, error_code, version from business_rules where is_active order by code",
        )
        tariff = await fetch_one(
            conn,
            "select coalesce(max(t.fee_pct), 0)::float as fee_pct from tariffs t where t.product_code = any(%s) and t.method = 'qr_sbp'",
            ([o["product_code"] for o in ops] or ["-"],),
        )
    fee_pct = float((tariff or {}).get("fee_pct") or 0)
    violations: list[dict[str, Any]] = []
    for r in rules:
        hits = []
        for o in ops:
            op = {**o, "operation_id": o["id"], "fee_amount": o.get("fee_amount") or 0}
            ctx = {
                "operation": op,
                "tariff": {"fee_pct": fee_pct},
                "ledger": {"kind": "debit" if (op.get("amount_rub") or 0) > 0 else None},
            }
            try:
                if evaluate(r["condition"], ctx):
                    hits.append(op)
            except Exception:  # noqa: BLE001
                continue
        if hits:
            amount = float(sum(h.get("fee_amount") or 0 for h in hits)) if r["action"] == "refund_fee" else None
            violations.append(
                {
                    "rule_code": r["code"],
                    "rule_version": r["version"],
                    "action": r["action"],
                    "owner_team_code": r["owner_team_code"],
                    "error_code": r["error_code"],
                    "amount_rub": amount,
                    "operation_ids": [h["id"] for h in hits],
                    "within_limit": amount is None
                    or not (r["limits"] or {}).get("max_amount_rub")
                    or amount <= float(r["limits"]["max_amount_rub"]),
                }
            )
    return JSONResponse(
        jsonable_encoder(
            {
                "event_type": "agent.rule_violation",
                "run_id": run_id,
                "sim_time": sim_time,
                "operation_id": body.operation_id,
                "client_id": body.client_id or (ops[0]["client_id"] if ops else None),
                "operations_checked": len(ops),
                "rules_checked": len(rules),
                "matched": violations,
            }
        )
    )


@router.get("/api/rules/evaluations", summary="История срабатываний правил")
async def get_rules_evaluations(
    run_id: str | None = Query(None),
    signal_id: int | None = Query(None),
    rule_code: str | None = Query(None),
    result: str | None = Query(None, description="matched | not_matched | error"),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("e.run_id = %s")
            args.append(rid)
        if signal_id is not None:
            where.append("e.signal_id = %s")
            args.append(signal_id)
        if rule_code:
            where.append("e.rule_code = %s")
            args.append(rule_code)
        if result:
            where.append("e.result = %s")
            args.append(result)
        if cursor:
            where.append("e.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"select e.id, e.run_id, e.signal_id, e.agent_run_id, e.rule_code, e.rule_version, e.result, e.evidence, e.proposed_action, "
            f"e.amount_rub::float as amount_rub, e.latency_ms, e.created_at, s.public_id as signal_public_id "
            f"from rule_evaluations e left join signals s on s.id = e.signal_id where {' and '.join(where)} order by e.id desc limit %s",
            (*args, limit + 1),
        )
        summary = await fetch_all(
            conn,
            f"select e.rule_code, e.result, count(*) as n from rule_evaluations e where {' and '.join(where[:2] if rid is not None else where[:1])} group by 1, 2 order by 1, 2",
            tuple(args[:1]) if rid is not None else (),
        )
    items = rows[:limit]
    next_cursor = str(items[-1]["id"]) if len(rows) > limit and items else None
    return JSONResponse(jsonable_encoder({"items": items, "next_cursor": next_cursor, "summary": summary}))
