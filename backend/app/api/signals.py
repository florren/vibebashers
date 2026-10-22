"""Роутер тега `signals` (OpenAPI 1.4.0). Реализовано (B04/T-207): лента, карточка, ввод жюри-режима. Отложенные — T-087."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.common import agent_service, db, fetch_all, fetch_one, page, resolve_run_id
from app.ingest.normalizer import IngestError, create_signal, from_api_signal

router = APIRouter(tags=["signals"])

SIGNAL_SQL = (
    "select s.id, s.public_id, s.channel_code, s.channel_subtype, s.external_contact, s.text, s.received_sim, s.status, s.origin, s.classification, s.sentiment, s.geo, s.run_id, "
    "coalesce(c.region_code, s.geo->>'region_code') as region_code, "
    "case when c.id is null then null else jsonb_build_object('id', c.id, 'public_id', c.public_id, 'display_name', c.display_name, 'segment_code', c.segment_code, 'region_code', c.region_code, 'city_name', ci.name_ru, 'churn_risk', c.churn_risk, 'is_active', c.is_active) end as client, "
    "coalesce((select array_agg(isg.incident_id order by isg.incident_id) from incident_signals isg where isg.signal_id = s.id), '{}') as incident_ids "
    "from signals s left join clients c on c.id = s.client_id left join cities ci on ci.id = c.city_id"
)


@router.get("/api/signals", summary="Лента сигналов с фильтрами")
async def get_signals(
    request: Request,
    run_id: str = Query(default="current"),
    q: str | None = None,
    channel: list[str] | None = Query(default=None),
    signal_type: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    segment: list[str] | None = Query(default=None),
    product: list[str] | None = Query(default=None),
    region_code: str | None = None,
    city_id: int | None = None,
    criticality: str | None = None,
    since_sim: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("s.run_id = %s")
            args.append(rid)
        if q:
            where.append("s.text ilike %s")
            args.append(f"%{q}%")
        for expr, val in (
            ("s.channel_code = any(%s)", channel or None),
            ("s.classification->>'signal_type' = any(%s)", signal_type or None),
            ("s.status = any(%s)", status or None),
            ("c.segment_code = any(%s)", segment or None),
            ("s.classification->>'product' = any(%s)", product or None),
            ("coalesce(c.region_code, s.geo->>'region_code') = %s", region_code),
            ("c.city_id = %s", city_id),
            ("s.classification->>'criticality' = %s", criticality),
            ("s.received_sim >= %s", since_sim),
        ):
            if val is not None:
                where.append(expr)
                args.append(val)
        if cursor:
            where.append("s.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn, f"{SIGNAL_SQL} where {' and '.join(where)} order by s.id desc limit %s", [*args, limit]
        )  # noqa: S608
    return page(rows, limit)


class SignalCreate(BaseModel):
    channel_code: str
    channel_subtype: str | None = None
    client_id: int | None = None
    external_contact: dict[str, Any] | None = None
    text: str = Field(min_length=3, max_length=4000)
    compare_with_mock: bool = True
    voice_meta: dict[str, Any] | None = None
    external_id: str | None = None


@router.post("/api/signals", summary="Жюри-режим — ввести сообщение клиента вручную", status_code=202)
async def post_signals(request: Request, body: SignalCreate) -> Any:
    svc = agent_service(request)
    msg = from_api_signal(body.model_dump(exclude_none=True), origin="jury", source_code="api")
    async with db() as conn:
        try:
            res = await create_signal(conn, msg, source_code="api", emit_event=False)
        except IngestError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if res["status"] == "rejected":
        raise HTTPException(status_code=422, detail=res["error"])
    task = svc.submit(int(res["signal_id"]))
    await task  # жюри ждёт результат: проход на mock ≈ 1 с, на live ≤ 30 с
    async with db() as conn:
        run = await fetch_one(
            conn, "select id from agent_runs where signal_id = %s order by id desc limit 1", (res["signal_id"],)
        )
    return {"signal_id": res["signal_id"], "agent_run_id": run["id"] if run else None, "compare_run_id": None}


@router.get("/api/signals/deferred", summary="Отложенные («спящие») обращения с причиной и временем пробуждения")
async def get_signals_deferred(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> Any:
    async with db() as conn:
        rows = await fetch_all(
            conn,
            "select f.id as followup_id, f.signal_id, f.incident_id, f.wake_sim, f.reason, f.status, s.text, s.channel_code, s.status as signal_status from followups f join signals s on s.id = f.signal_id where f.status = 'scheduled' order by f.wake_sim limit %s",
            (limit,),
        )
    return {"items": rows, "next_cursor": None}


@router.get("/api/signals/{id}", summary="Сигнал с классификацией, решением, связанными инцидентами и запусками агента")
async def get_signals_id(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        row = await fetch_one(conn, f"{SIGNAL_SQL} where s.id = %s", (id,))  # noqa: S608
        if not row:
            raise HTTPException(status_code=404, detail="сигнал не найден")
        decision = await fetch_one(conn, "select decision from signals where id = %s", (id,))
        incidents = await fetch_all(
            conn,
            "select i.id, i.public_id, i.title, i.incident_type, i.product_code, i.system_code, i.team_code, i.complexity, i.criticality, i.priority, i.status, i.flags, i.mass_impact, i.region_code, i.created_sim, i.sla_due_sim, i.sla_breached, i.outcome_class, i.problem_summary, i.routing_status, isg.link_type from incident_signals isg join incidents i on i.id = isg.incident_id where isg.signal_id = %s order by i.id",
            (id,),
        )
        runs = await fetch_all(
            conn,
            "select ar.id, ar.kind, ar.signal_id, 'default' as llm_profile_code, ar.prompt_version, ar.outcome, ar.needed_human, ar.total_tokens, ar.total_latency_ms, ar.started_at, ar.finished_at, (select node from agent_steps st where st.run_id = ar.id order by seq desc limit 1) as current_node from agent_runs ar where ar.signal_id = %s order by ar.id",
            (id,),
        )
        notifications = await fetch_all(
            conn,
            "select id, recipient_type, channel_code, template_code, subject, body, status, sent_sim, client_id, incident_id, team_code from notifications where signal_id = %s order by id",
            (id,),
        )
        followups = await fetch_all(
            conn, "select id, wake_sim, reason, status from followups where signal_id = %s order by id", (id,)
        )
    return {
        **row,
        "decision": (decision or {}).get("decision"),
        "incidents": incidents,
        "agent_runs": runs,
        "notifications": notifications,
        "followups": followups,
    }
