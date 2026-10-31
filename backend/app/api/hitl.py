"""Роутер тега `hitl` (OpenAPI 1.4.0). Реализовано (B04/T-076): очередь, карточка, решение человека → возобновление графа. Остальное — T-077."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.common import agent_service, db, fetch_all, fetch_one, page
from app.search.cases import case_search, related_entities
from app.sim.events import dumps
from app.trace.store import allowed_run

router = APIRouter(tags=["hitl"])

HITL_SQL = """
select hd.id,hd.public_id,hd.sim_run_id,(select r.public_id from sim_runs r where r.id=hd.sim_run_id) as run_public_id,hd.reason,hd.agent_proposal,hd.options,hd.recommendation,
 hd.requested_sim,hd.requested_at,hd.decision,hd.decided_by,hd.comment,hd.decided_sim,
 hd.agent_run_id,hd.incident_id,hd.task_id,ar.outcome as process_outcome,
 (hd.decision is null and ar.outcome='awaiting_human' and
   (select case when st.input->>'current_node'='wait_human' then st.output->>'human_decision_id' end from agent_steps st where st.run_id=ar.id and st.node='wait_human' order by st.seq desc limit 1)=hd.id::text) as can_resume,
 (hd.decided_by='timeout') as automatic_decision,
 (select count(*) from hitl_feedback f where f.human_decision_id=hd.id) as feedback_count,
 (select to_jsonb(t) from tasks t where t.id=hd.task_id and t.run_id=hd.sim_run_id) as task,
 case when s.id is null then null else jsonb_build_object('id',s.id,'public_id',s.public_id,'channel_code',s.channel_code,'text',s.text,
  'received_sim',s.received_sim,'status',s.status,'origin',s.origin,'classification',s.classification,
  'sentiment',s.sentiment,'region_code',coalesce(c.region_code,s.geo->>'region_code'),
  'client',case when c.id is null then null else jsonb_build_object('id',c.id,'public_id',c.public_id,
  'display_name',c.display_name,'segment_code',c.segment_code,'region_code',c.region_code,'churn_risk',c.churn_risk) end) end as signal,
 case when i.id is null then null else jsonb_build_object('id',i.id,'public_id',i.public_id,'title',i.title,
  'status',i.status,'team_code',i.team_code,'criticality',i.criticality) end as incident,
 coalesce((select jsonb_agg(jsonb_build_object('id',inc.id,'public_id',inc.public_id,'status',inc.status) order by inc.id)
  from incidents inc where inc.run_id=hd.sim_run_id and inc.id=any(array(
  select hd.incident_id union select ar.incident_id union select x.incident_id from incident_signals x where x.signal_id=s.id))), '[]') as related_incidents,
 coalesce((select jsonb_agg(jsonb_build_object('kind','escalation','ref',e.public_id) order by e.id)
  from escalations e where e.run_id=hd.sim_run_id and (e.human_decision_id=hd.id or e.signal_id=s.id)), '[]') as escalations,
 extract(epoch from (coalesce(hd.decided_at,now())-hd.requested_at))/60.0 as waiting_minutes
from human_decisions hd left join signals s on s.id=hd.signal_id
left join clients c on c.id=s.client_id left join agent_runs ar on ar.id=hd.agent_run_id
left join incidents i on i.run_id=hd.sim_run_id and i.id=coalesce(hd.incident_id,ar.incident_id,
 (select x.incident_id from incident_signals x join incidents inc on inc.id=x.incident_id and inc.run_id=hd.sim_run_id where x.signal_id=s.id order by x.incident_id limit 1))
"""


def _item(row: dict[str, Any]) -> dict[str, Any]:
    cls = (row["signal"] or {}).get("classification") or {}
    summary = f"{cls.get('summary_ru') or (row['signal'] or {}).get('text', '')[:160]} Тип: {cls.get('signal_type') or '—'}, критичность {cls.get('criticality') or '—'}, уверенность {float(cls.get('confidence') or 0):.2f}."
    return {
        **row,
        "can_resume": bool(row.get("can_resume")),
        "automatic_decision": bool(row.get("automatic_decision")),
        "context_summary_ru": summary,
        "waiting_minutes": round(float(row["waiting_minutes"] or 0), 1),
    }


@router.get("/api/hitl/queue", summary="Поиск HITL и связанных сущностей, включая автоматическое продолжение")
async def get_hitl_queue(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: int | None = Query(None, gt=0),
    include_decided: bool = False,
    run_id: str = "all",
    q: str | None = Query(None, max_length=200),
) -> Any:
    async with db() as conn:
        where = ["true" if include_decided or (q and q.strip()) else "(hd.decision is null or hd.decided_by='timeout')"]
        args: list[Any] = []
        rid = await allowed_run(conn, run_id)
        if rid is not None:
            where.append("hd.sim_run_id=%s")
            args.append(rid)
        cte, search_args, pattern = await case_search(conn, q.strip()) if q and q.strip() else ("", [], "")
        if q and q.strip():
            predicate = "(s.text ilike %s or s.public_id ilike %s or i.public_id ilike %s or hd.public_id ilike %s or hd.reason ilike %s or hd.comment ilike %s or exists (select 1 from tasks t where t.id=hd.task_id and t.public_id ilike %s) or exists (select 1 from agent_runs a where a.id=hd.agent_run_id and a.public_id ilike %s) or exists (select 1 from hitl_feedback f where f.human_decision_id=hd.id and f.comment ilike %s)"
            args.extend([pattern] * 9)
            if cte:
                predicate += " or s.id in (select id from case_signals) or i.id in (select id from case_incidents)"
            where.append(predicate + ")")
        refs, truncated = await related_entities(conn, cte, search_args, rid)
        condition = " and ".join(where)
        total = await fetch_one(
            conn, f"{cte}select count(*) as total from ({HITL_SQL} where {condition}) entries", [*search_args, *args]
        )
        if cursor is not None:
            condition += " and hd.id < %s"
            args.append(cursor)
        rows = await fetch_all(
            conn, f"{cte}{HITL_SQL} where {condition} order by hd.id desc limit %s", [*search_args, *args, limit]
        )
    return {
        **page([_item(r) for r in rows], limit),
        "total": total["total"] if total else 0,
        "related_entities": refs,
        "related_entities_truncated": truncated,
    }


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
    comment: str | None = Field(None, max_length=4000)
    delegate_to: str | None = None
    use_as_fewshot: bool = True
    decided_by: str = Field(default="operator", min_length=1, max_length=120)


@router.post("/api/hitl/{id}", summary="Решение человека — возвращается в граф агента")
async def post_hitl_id(request: Request, id: int, body: HitlDecisionBody) -> Any:  # noqa: A002
    async with db() as conn:
        async with conn.transaction():
            locked = await fetch_one(conn, "select id from human_decisions where id=%s for update", (id,))
            if not locked:
                raise HTTPException(404, "запрос HITL не найден")
            row = await fetch_one(conn, f"{HITL_SQL} where hd.id=%s", (id,))
            if not row:
                raise HTTPException(404, "запрос HITL не найден")
            if row["decision"] is not None:
                raise HTTPException(409, "Уже решено; дополнительную информацию передайте через журнал ответа")
            resume = bool(row["can_resume"])
            if (
                not resume
                and row["agent_run_id"] is not None
                and row["process_outcome"] is None
                and (row["agent_proposal"] or {}).get("kind") != "escalation"
            ):
                raise HTTPException(409, "Граф формирует запрос; повторите решение после готовности карточки")
            svc = agent_service(request) if resume else None
            if not resume and body.decision not in ("accept", "reject"):
                raise HTTPException(409, "Процесс уже продолжается; используйте журнал информации оператора")
            st = await fetch_one(conn, "select sim_time from sim_state where id=1")
            sim_time = st["sim_time"] if st else dt.datetime.now(dt.UTC)
            modified = (
                body.modified_proposal
                if body.decision == "modify"
                else ({"delegate_to": body.delegate_to} if body.delegate_to else None)
            )
            await conn.execute(
                "update human_decisions set decision=%s,modified_proposal=%s::jsonb,decided_by=%s,comment=%s,decided_sim=%s,decided_at=now(),use_as_fewshot=%s where id=%s",
                (
                    body.decision,
                    dumps(modified) if modified else None,
                    body.decided_by,
                    body.comment,
                    sim_time,
                    body.use_as_fewshot and resume,
                    id,
                ),
            )
            await conn.execute(
                "select pg_notify('hitl',%s)",
                (dumps({"type": "decided", "data": {"human_decision_id": id, "decision": body.decision}}),),
            )
    if svc is not None:
        await svc.resume(id, sim_time)
    async with db() as conn:
        out = await fetch_one(conn, f"{HITL_SQL} where hd.id=%s", (id,))
    return _item(out or {})


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    comment: str = Field(min_length=1, max_length=4000)
    recorded_by: str = Field(default="operator", min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=120)


@router.get("/api/hitl/{id}/feedback", summary="История информации оператора после продолжения процесса")
async def get_hitl_feedback(
    id: int, limit: int = Query(25, ge=1, le=100), cursor: int | None = Query(None, gt=0)
) -> Any:
    async with db() as conn:
        if not await fetch_one(conn, "select id from human_decisions where id=%s", (id,)):
            raise HTTPException(404, "запрос HITL не найден")
        rows = await fetch_all(
            conn,
            "select f.*,p.status as processing_status,p.agent_run_id,ar.public_id as review_run_ref,p.review,p.applied_at,p.error as processing_error from hitl_feedback f left join hitl_feedback_processing p on p.feedback_id=f.id left join agent_runs ar on ar.id=p.agent_run_id where f.human_decision_id=%s and (%s::bigint is null or f.id<%s) order by f.id desc limit %s",
            (id, cursor, cursor, limit),
        )
    return page(rows, limit)


@router.post("/api/hitl/{id}/feedback", status_code=201, summary="Добавить информацию без повторного выполнения графа")
async def post_hitl_feedback(id: int, body: FeedbackBody) -> Any:
    async with db() as conn, conn.transaction():
        hd = await fetch_one(conn, "select id from human_decisions where id=%s for update", (id,))
        if not hd:
            raise HTTPException(404, "запрос HITL не найден")
        existing = await fetch_one(
            conn,
            "select * from hitl_feedback where human_decision_id=%s and idempotency_key=%s",
            (id, body.idempotency_key),
        )
        if existing:
            if existing["comment"] != body.comment or existing["recorded_by"] != body.recorded_by:
                raise HTTPException(409, "Ключ повтора уже использован для другого ответа")
            return existing
        st = await fetch_one(conn, "select sim_time from sim_state where id=1")
        row = await fetch_one(
            conn,
            "insert into hitl_feedback(human_decision_id,idempotency_key,comment,recorded_by,recorded_sim) values (%s,%s,%s,%s,%s) returning *",
            (
                id,
                body.idempotency_key,
                body.comment,
                body.recorded_by,
                st["sim_time"] if st else dt.datetime.now(dt.UTC),
            ),
        )
        await conn.execute(
            "select pg_notify('hitl',%s)", (dumps({"type": "feedback", "data": {"human_decision_id": id}}),)
        )
    return row
