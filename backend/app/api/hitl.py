"""Роутер тега `hitl` (OpenAPI 1.4.0). Реализовано (B04/T-076): очередь, карточка, решение человека → возобновление графа. Остальное — T-077."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.common import agent_service, db, fetch_all, fetch_one, page
from app.sim.events import dumps

router = APIRouter(tags=["hitl"])

HITL_SQL = (
    "select hd.id, hd.reason, hd.agent_proposal, hd.options, hd.recommendation, hd.requested_sim, hd.requested_at, hd.decision, hd.decided_by, hd.comment, hd.decided_sim, hd.agent_run_id, hd.incident_id, hd.task_id, "
    "jsonb_build_object('id', s.id, 'public_id', s.public_id, 'channel_code', s.channel_code, 'text', s.text, 'received_sim', s.received_sim, 'status', s.status, 'origin', s.origin, 'classification', s.classification, 'sentiment', s.sentiment, 'region_code', coalesce(c.region_code, s.geo->>'region_code'), "
    "  'client', case when c.id is null then null else jsonb_build_object('id', c.id, 'public_id', c.public_id, 'display_name', c.display_name, 'segment_code', c.segment_code, 'region_code', c.region_code, 'churn_risk', c.churn_risk) end) as signal, "
    "case when i.id is null then null else jsonb_build_object('id', i.id, 'public_id', i.public_id, 'title', i.title, 'status', i.status, 'team_code', i.team_code, 'criticality', i.criticality) end as incident, "
    "extract(epoch from (coalesce(hd.decided_at, now()) - hd.requested_at)) / 60.0 as waiting_minutes "
    "from human_decisions hd join signals s on s.id = hd.signal_id left join clients c on c.id = s.client_id left join incidents i on i.id = hd.incident_id"
)


def _item(row: dict[str, Any]) -> dict[str, Any]:
    cls = (row["signal"] or {}).get("classification") or {}
    summary = f"{cls.get('summary_ru') or (row['signal'] or {}).get('text', '')[:160]} Тип: {cls.get('signal_type') or '—'}, критичность {cls.get('criticality') or '—'}, уверенность {cls.get('confidence', 0):.2f}."
    return {
        **row,
        "task": None,
        "context_summary_ru": summary,
        "waiting_minutes": round(float(row["waiting_minutes"] or 0), 1),
    }


@router.get("/api/hitl/queue", summary="Очередь «Требует решения»")
async def get_hitl_queue(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
    include_decided: bool = False,
) -> Any:
    async with db() as conn:
        where = "true" if include_decided else "hd.decision is null"
        args: list[Any] = []
        if cursor:
            where += " and hd.id < %s"
            args.append(int(cursor))
        rows = await fetch_all(conn, f"{HITL_SQL} where {where} order by hd.id desc limit %s", [*args, limit])  # noqa: S608
    return page([_item(r) for r in rows], limit)


@router.get("/api/hitl/{id}", summary="Карточка HITL (сигнал, контекст, предложение агента, варианты)")
async def get_hitl_id(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        row = await fetch_one(conn, f"{HITL_SQL} where hd.id = %s", (id,))  # noqa: S608
    if not row:
        raise HTTPException(status_code=404, detail="запрос HITL не найден")
    return _item(row)


class HitlDecisionBody(BaseModel):
    decision: Literal["accept", "modify", "reject", "delegate"]
    modified_proposal: dict[str, Any] | None = None
    comment: str | None = None
    delegate_to: str | None = None
    use_as_fewshot: bool = True
    decided_by: str = "operator"


@router.post("/api/hitl/{id}", summary="Решение человека — возвращается в граф агента")
async def post_hitl_id(request: Request, id: int, body: HitlDecisionBody) -> Any:  # noqa: A002
    svc = agent_service(request)
    async with db() as conn:
        row = await fetch_one(conn, "select id, decision from human_decisions where id = %s", (id,))
        if not row:
            raise HTTPException(status_code=404, detail="запрос HITL не найден")
        if row["decision"] is not None:
            raise HTTPException(status_code=409, detail="уже решено")
        st = await fetch_one(conn, "select sim_time from sim_state where id = 1")
        sim_time = st["sim_time"] if st else dt.datetime.now(dt.UTC)
        modified = (
            body.modified_proposal
            if body.decision == "modify"
            else ({"delegate_to": body.delegate_to} if body.delegate_to else None)
        )
        await conn.execute(
            "update human_decisions set decision = %s, modified_proposal = %s::jsonb, decided_by = %s, comment = %s, decided_sim = %s, decided_at = now(), use_as_fewshot = %s where id = %s",
            (
                body.decision,
                dumps(modified) if modified else None,
                body.decided_by,
                body.comment,
                sim_time,
                body.use_as_fewshot,
                id,
            ),
        )
        await conn.execute(
            "select pg_notify('hitl', %s)",
            (dumps({"type": "decided", "data": {"human_decision_id": id, "decision": body.decision}}),),
        )
    await svc.resume(id, sim_time)
    async with db() as conn:
        out = await fetch_one(conn, f"{HITL_SQL} where hd.id = %s", (id,))  # noqa: S608
    return _item(out or {})
