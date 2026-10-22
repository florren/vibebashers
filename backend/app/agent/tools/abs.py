"""Инструменты агента для Mock-АБС и публичной ленты (T-175/T-176): refund_fee, get_account_balance, find_affected_clients, publish_public_reply."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.abs import service as abs_svc
from app.agent.tools.base import ToolContext, tool
from app.feed import service as feed_svc


@tool("refund_fee")
async def refund_fee(
    ctx: ToolContext, operation_id: int, amount_rub: float | None, rule_id: str | None, reason: str
) -> dict[str, Any]:
    """Возврат ошибочной комиссии: только при matched-правиле по операции, один раз на fee-проводку (идемпотентно)."""
    res = await abs_svc.refund_fee(
        ctx.conn,
        run_id=ctx.run_id,
        operation_id=operation_id,
        amount_rub=amount_rub,
        rule_id=rule_id,
        reason=reason,
        posted_sim=ctx.sim_time,
        correlation_id=uuid.uuid5(uuid.NAMESPACE_URL, f"refund:{ctx.run_id}:{operation_id}"),
        agent_run_id=ctx.agent_run_id,
        created_by="agent",
        require_rule=True,
    )
    await ctx.notify(
        "abs", "refund", {"operation_id": operation_id, **{k: v for k, v in res.items() if k != "client_id"}}
    )
    return res


@tool("get_account_balance")
async def get_account_balance(ctx: ToolContext, client_id: int) -> dict[str, Any]:
    acc = await abs_svc.ensure_account(ctx.conn, client_id)
    return {"client_id": client_id, **acc}


@tool("find_affected_clients")
async def find_affected_clients(ctx: ToolContext, error_code: str, window_hours: int = 72) -> dict[str, Any]:
    rows = await abs_svc.find_affected(
        ctx.conn, run_id=ctx.run_id, error_code=error_code, since_sim=ctx.sim_time - dt.timedelta(hours=window_hours)
    )
    pending = [r for r in rows if not r["refunded"]]
    return {
        "error_code": error_code,
        "affected_count": len(rows),
        "pending_count": len(pending),
        "pending_fee_rub": round(sum(r["fee_amount"] for r in pending), 2),
        "operations": [{k: v for k, v in r.items() if k != "started_sim"} for r in pending[:50]],
    }


@tool("publish_public_reply")
async def publish_public_reply(
    ctx: ToolContext,
    post_id: int,
    text: str,
    incident_id: int | None = None,
    link_to_dm: bool = True,
    escalate_to_dm: bool = False,
) -> dict[str, Any]:
    """Публичный ответ под постом: без ПДн и обещаний, с приглашением в личный канал (ТЗ 21.5)."""
    body = text.strip()
    if link_to_dm and "личн" not in body.lower():
        body += " Подробности отправим в личные сообщения."
    res = await feed_svc.publish_reply(
        ctx.conn,
        run_id=ctx.run_id,
        post_id=post_id,
        text=body,
        author="agent",
        sim_time=ctx.sim_time,
        incident_id=incident_id,
        agent_run_id=ctx.agent_run_id,
        llm_source=ctx.llm_source if ctx.llm_source in ("live", "replay", "mock") else None,
        escalate_to_dm=escalate_to_dm,
    )
    await ctx.notify(
        "feed",
        "reply",
        {"post_id": post_id, **{k: str(v) if isinstance(v, dt.datetime) else v for k, v in res.items()}},
    )
    return res
