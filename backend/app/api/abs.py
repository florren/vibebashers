"""Роутер тега `abs` (T-171): счета клиента, проводки, возвраты по решению человека. Деньги двигаются только через app.abs.service."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.abs import service as abs_svc
from app.api._compliance_support import run_context
from app.api.common import db, fetch_all, resolve_run_id
from app.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["abs"])


@router.get("/api/abs/accounts/{client_id}", summary="Счета клиента и последние проводки (виджет «АБС (эмуляция)»)")
async def get_abs_accounts_client_id(client_id: int, entries_limit: int = Query(20, ge=1, le=200)) -> Any:
    async with db() as conn:
        view = await abs_svc.accounts_view(conn, client_id, entries_limit)
    if view is None:
        raise HTTPException(status_code=404, detail=f"клиент {client_id} не найден")
    return JSONResponse(jsonable_encoder(view))


@router.get("/api/abs/ledger", summary="Проводки с фильтрами (для экрана «Данные в БД» и проверок)")
async def get_abs_ledger(
    run_id: str | None = Query(None),
    client_id: int | None = Query(None),
    operation_id: int | None = Query(None),
    kind: str | None = Query(None, description="через запятую: debit,credit,fee,refund,reversal"),
    rule_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> Any:
    kinds = [k for k in (kind or "").split(",") if k]
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("l.run_id = %s")
            args.append(rid)
        if client_id is not None:
            where.append("a.client_id = %s")
            args.append(client_id)
        if operation_id is not None:
            where.append("l.operation_id = %s")
            args.append(operation_id)
        if kinds:
            where.append("l.kind = any(%s)")
            args.append(kinds)
        if rule_id:
            where.append("l.rule_id = %s")
            args.append(rule_id)
        if cursor:
            where.append("l.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"""
            select l.id, l.account_id, a.client_id, l.operation_id, l.kind, l.amount::float as amount, l.counterpart, l.posted_at, l.posted_sim,
                   l.correlation_id, l.refund_of_entry_id, l.rule_id, l.agent_run_id, l.created_by
            from ledger_entries l join accounts a on a.id = l.account_id
            where {" and ".join(where)} order by l.id desc limit %s
            """,
            (*args, limit + 1),
        )
    items = rows[:limit]
    next_cursor = str(items[-1]["id"]) if len(rows) > limit and items else None
    return JSONResponse(jsonable_encoder({"items": items, "next_cursor": next_cursor}))


class RefundItem(BaseModel):
    operation_id: int
    amount_rub: float = Field(gt=0)
    rule_id: str | None = None
    correlation_id: uuid.UUID


class RefundBatch(BaseModel):
    items: list[RefundItem] = Field(min_length=1, max_length=500)
    reason: str = Field(max_length=400)
    incident_id: int | None = None
    human_decision_id: int | None = None


@router.post(
    "/api/abs/refunds", summary="Возврат по решению человека (массовый или сверх лимита автономии)", status_code=202
)
async def post_abs_refunds(request: Request, body: RefundBatch) -> Any:
    """Служебный вход HITL: проводки по списку операций, идемпотентно по correlation_id; агент возвращает только инструментом refund_fee."""
    job_id = str(uuid.uuid4())
    accepted = skipped = failed = 0
    errors: list[dict[str, Any]] = []
    async with db() as conn:
        run_id, sim_time = await run_context(request, conn)
        for it in body.items:
            try:
                res = await abs_svc.refund_fee(
                    conn,
                    run_id=run_id,
                    operation_id=it.operation_id,
                    amount_rub=it.amount_rub,
                    rule_id=it.rule_id,
                    reason=f"решение человека: {body.reason}",
                    posted_sim=sim_time,
                    correlation_id=it.correlation_id,
                    created_by="human",
                    require_rule=False,
                )
            except abs_svc.AbsError as exc:
                failed += 1
                errors.append({"operation_id": it.operation_id, "error": str(exc)})
                continue
            if res.get("duplicate"):
                skipped += 1
            else:
                accepted += 1
        if body.incident_id and accepted:
            await conn.execute(
                "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) "
                "select id, status, status, 'human', %s, %s, %s from incidents where id = %s",
                (
                    str(body.human_decision_id or "operator"),
                    f"Возвраты по решению человека: {accepted} шт. ({body.reason})"[:400],
                    sim_time,
                    body.incident_id,
                ),
            )
    log.info("abs_refund_batch", job_id=job_id, accepted=accepted, skipped=skipped, failed=failed)
    await asyncio.sleep(0)
    return JSONResponse(
        {
            "accepted": accepted,
            "skipped_duplicates": skipped,
            "failed": failed,
            "errors": errors[:20],
            "job_id": job_id,
        },
        status_code=202,
    )
