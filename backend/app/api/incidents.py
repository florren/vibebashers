"""Роутер тега `incidents` (OpenAPI 1.4.0). Реализовано (B04): список, карточка, история, сигналы, коммуникации. Экономика/действия/команды — T-089."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.common import db, fetch_all, fetch_one, page, resolve_run_id
from app.economics import dcltv
from app.errors import NotImplementedYet, Problem

router = APIRouter(tags=["incidents"])


INCIDENT_SQL = (
    "select i.id, i.public_id, i.title, i.incident_type, i.product_code, i.system_code, i.error_code, i.team_code, i.co_team_codes, i.complexity, i.criticality, i.priority, i.status, i.flags, i.mass_impact, "
    "i.region_code, i.created_sim, i.sla_due_sim, i.take_due_sim, i.report_due_sims, i.taken_sim, i.resolved_sim, i.closed_sim, i.sla_breached, i.outcome_class, i.problem_summary, i.routing_status, i.root_cause, i.resolution_summary, i.primary_client_id, i.fault_id, i.agent_run_id, i.run_id, "
    "t.channel, t.sentiment, "
    "(select min(d) from unnest(i.report_due_sims) d where d > st.sim_time) as next_report_due_sim, "
    "greatest(0, least(100, round(100 * extract(epoch from (i.sla_due_sim - st.sim_time)) / nullif(extract(epoch from (i.sla_due_sim - i.created_sim)), 0)))) as sla_remaining_pct "
    "from incidents i cross join (select sim_time from sim_state where id = 1) st left join v_tickets t on t.incident_id = i.id"
)
SORTS = {
    "created": "i.created_sim desc",
    "sla": "i.sla_due_sim asc",
    "priority": "i.priority asc, i.created_sim desc",
    "id": "i.id desc",
}


@router.get("/api/incidents", summary="Инциденты (доска/таблица)")
async def get_incidents(
    request: Request,
    run_id: str = Query(default="current"),
    status: list[str] | None = Query(default=None),
    team: str | None = None,
    product: str | None = None,
    criticality: str | None = None,
    complexity: str | None = None,
    incident_type: str | None = None,
    region_code: str | None = None,
    sla_risk: str | None = None,
    routing_status: str | None = None,
    sentiment: str | None = None,
    sort: str = Query(default="id"),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("i.run_id = %s")
            args.append(rid)
        for expr, val in (
            ("i.status = any(%s)", status or None),
            ("i.team_code = %s", team),
            ("i.product_code = %s", product),
            ("i.criticality = %s", criticality),
            ("i.complexity = %s", complexity),
            ("i.incident_type = %s", incident_type),
            ("i.region_code = %s", region_code),
            ("i.routing_status = %s", routing_status),
            ("t.sentiment = %s", sentiment),
        ):
            if val is not None:
                where.append(expr)
                args.append(val)
        if sla_risk == "breached":
            where.append("i.status not in ('closed','resolved','rejected','duplicate') and i.sla_breached")
        elif sla_risk in ("any", "warning", "true", "1"):
            where.append(
                "i.status not in ('closed','resolved','rejected','duplicate') and (i.sla_breached or i.sla_due_sim < st.sim_time + interval '1 day')"
            )
        if cursor and sort == "id":
            where.append("i.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"{INCIDENT_SQL} where {' and '.join(where)} order by {SORTS.get(sort, SORTS['id'])} limit %s",
            [*args, limit],
        )  # noqa: S608
    return page(rows, limit) if sort == "id" else {"items": rows, "next_cursor": None}


@router.get("/api/incidents/{id}", summary="Карточка инцидента (сводка + клиент 360 + SLA + экономика)")
async def get_incidents_id(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        row = await fetch_one(conn, f"{INCIDENT_SQL} where i.id = %s", (id,))  # noqa: S608
        if not row:
            raise HTTPException(status_code=404, detail="инцидент не найден")
        client = (
            await fetch_one(
                conn,
                "select c.id, c.public_id, c.display_name, c.segment_code, c.region_code, ci.name_ru as city_name, c.churn_risk, c.is_active from clients c join cities ci on ci.id = c.city_id where c.id = %s",
                (row["primary_client_id"],),
            )
            if row["primary_client_id"]
            else None
        )
        decision = await fetch_one(
            conn,
            "select s.decision from incident_signals isg join signals s on s.id = isg.signal_id where isg.incident_id = %s order by (isg.link_type = 'primary') desc limit 1",
            (id,),
        )
        fault = (
            await fetch_one(
                conn,
                "select id, system_code, error_code, started_sim, resolved_sim, impact_count, affected_clients from faults where id = %s",
                (row["fault_id"],),
            )
            if row["fault_id"]
            else None
        )
        regressions = await fetch_all(
            conn,
            "select id, system_code, error_code, started_sim, resolved_sim from faults where caused_by_incident_id = %s",
            (id,),
        )
        econ_row = await fetch_one(
            conn, "select breakdown, computed_sim from incident_economics where incident_id = %s", (id,)
        )
    econ = {**(econ_row["breakdown"] or {}), "computed_sim": econ_row["computed_sim"]} if econ_row else None
    d = (decision or {}).get("decision") or {}
    return {
        **row,
        "primary_client": client,
        "decision": d or None,
        "agent_rationale_ru": d.get("rationale_ru") or "",
        "fault": fault,
        "regressions": regressions,
        "economics": econ,
    }


@router.get("/api/incidents/{id}/history", summary="История статусов")
async def get_incidents_id_history(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        rows = await fetch_all(
            conn,
            "select id, from_status, to_status, actor_type, actor_ref, reason, changed_sim, changed_at from incident_status_history where incident_id = %s order by id",
            (id,),
        )
    return {"items": rows}


@router.get(
    "/api/incidents/{id}/artifacts",
    summary="Документы команды (RCA, решение о фиксе, промежуточные отчёты, релиз, проверка)",
)
async def get_incidents_id_artifacts(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/incidents/{id}/signals", summary="Связанные сигналы и логи систем")
async def get_incidents_id_signals(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        signals = await fetch_all(
            conn,
            "select s.id, s.public_id, s.channel_code, s.text, s.received_sim, s.status, s.origin, s.sentiment, s.client_id, s.classification, isg.link_type, isg.linked_sim from incident_signals isg join signals s on s.id = isg.signal_id where isg.incident_id = %s order by isg.linked_sim",
            (id,),
        )
        logs = await fetch_all(
            conn,
            "select l.id, l.system_code, l.level, l.error_code, l.message, l.logged_sim from system_logs l join incidents i on i.id = %s where (l.fault_id = i.fault_id and i.fault_id is not null) or (l.error_code = i.error_code and l.logged_sim between i.created_sim - interval '4 hours' and i.created_sim + interval '4 hours') order by l.logged_sim desc limit 50",
            (id,),
        )
    return {"signals": signals, "system_logs": logs}


@router.get("/api/incidents/{id}/communications", summary="Коммуникации с клиентом и реакции двойника")
async def get_incidents_id_communications(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        notifications = await fetch_all(
            conn,
            "select id, recipient_type, channel_code, template_code, subject, body, status, sent_sim, client_id, incident_id, team_code from notifications where incident_id = %s order by id",
            (id,),
        )
        reactions = await fetch_all(
            conn,
            "select id, client_id, state, since_sim, trigger from client_states where incident_id = %s order by id",
            (id,),
        )
    return {"notifications": notifications, "client_reactions": reactions}


@router.get("/api/incidents/{id}/economics", summary="Развёрнутый расчёт dCLTV по инциденту (все множители)")
async def get_incidents_id_economics(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        res = await dcltv.compute_incident(conn, id)
    if res is None:
        raise Problem(404, "Инцидент не найден")
    return res


@router.post("/api/incidents/{id}/actions", summary="Действие сотрудника CX над инцидентом")
async def post_incidents_id_actions(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/teams/load", summary="Нагрузка команд и соблюдение SLA (вкладка «Команды»)")
async def get_teams_load(request: Request) -> Any:
    raise NotImplementedYet("T-089")
