"""Роутер тега `incidents` (OpenAPI 1.4.0). Реализовано (B04): список, карточка, история, сигналы, коммуникации. Экономика/действия/команды — T-089."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.agent.tools.write import PII_RE, STATUS_TRANSITIONS
from app.api.common import db, fetch_all, fetch_one, page, resolve_run_id
from app.economics import dcltv
from app.errors import Problem
from app.sim.events import dumps

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
async def get_incidents_id_artifacts(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        rows = await fetch_all(
            conn,
            "select id, kind, title, body_md, meta, author_team, generated_by, due_sim, published_sim, (due_sim is not null and published_sim > due_sim) as is_late from incident_artifacts where incident_id = %s order by published_sim",
            (id,),
        )
    return rows


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


class ActionBody(BaseModel):
    action: Literal[
        "reroute",
        "reply_client",
        "close",
        "request_client_data",
        "escalate",
        "reject",
        "mark_duplicate",
        "change_priority",
        "take",
    ]
    team_code: str | None = None
    text: str | None = Field(None, max_length=2000)
    channel_code: str | None = None
    duplicate_of_id: int | None = None
    priority: int | None = Field(None, ge=1, le=4)
    reason: str | None = Field(None, max_length=1000)
    actor: str = "operator"


async def _transition(
    conn: Any, inc: dict[str, Any], to_status: str, actor: str, reason: str | None, sim_time: Any
) -> None:
    cur = str(inc["status"])
    if to_status == cur:
        return
    if to_status not in STATUS_TRANSITIONS.get(cur, set()):
        raise Problem(409, f"Переход {cur} → {to_status} недопустим по FSM ТЗ 8.3")
    extra, args = "", [to_status]
    if to_status == "in_progress":
        extra, args = ", taken_sim = coalesce(taken_sim, %s)", [to_status, sim_time]
    elif to_status == "resolved":
        extra, args = ", resolved_sim = %s, sla_breached = (%s > sla_due_sim)", [to_status, sim_time, sim_time]
    elif to_status == "closed":
        extra, args = ", closed_sim = %s", [to_status, sim_time]
    await conn.execute(f"update incidents set status = %s{extra}, updated_at = now() where id = %s", (*args, inc["id"]))  # noqa: S608 — extra фиксирован кодом
    await conn.execute(
        "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, %s, %s, 'human', %s, %s, %s)",
        (inc["id"], cur, to_status, actor, reason, sim_time),
    )
    inc["status"] = to_status


@router.post("/api/incidents/{id}/actions", summary="Действие сотрудника CX над инцидентом")
async def post_incidents_id_actions(request: Request, id: int, body: ActionBody) -> Any:  # noqa: A002
    """Ручные действия оператора поверх FSM ТЗ 8.3: все переходы пишутся в историю с actor_type = human, уведомления — в центр уведомлений."""
    async with db() as conn:
        inc = await fetch_one(
            conn,
            "select id, run_id, status, team_code, priority, primary_client_id, agent_run_id, title from incidents where id = %s",
            (id,),
        )
        if not inc:
            raise Problem(404, "Инцидент не найден")
        now = await fetch_one(conn, "select sim_time from sim_state where id = 1")
        sim_time = (now or {}).get("sim_time") or dt.datetime.now(dt.UTC)
        reason = body.reason or body.text
        a = body.action
        if a == "take":
            if inc["status"] in ("new", "classified"):
                await _transition(conn, inc, "routed", body.actor, "взят оператором: маршрутизация", sim_time)
            await _transition(conn, inc, "in_progress", body.actor, reason or "взят в работу оператором", sim_time)
        elif a == "reroute":
            if not body.team_code:
                raise Problem(422, "Укажите team_code")
            team = await fetch_one(conn, "select code from teams where code = %s", (body.team_code,))
            if not team:
                raise Problem(404, "Команда не найдена")
            await conn.execute(
                "update incidents set team_code = %s, routing_status = 'routed', updated_at = now() where id = %s",
                (body.team_code, id),
            )
            if inc["status"] in ("new", "classified", "awaiting_human", "escalated"):
                await _transition(
                    conn, inc, "routed", body.actor, reason or f"перенаправлен в {body.team_code}", sim_time
                )
            else:
                await conn.execute(
                    "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, %s, %s, 'human', %s, %s, %s)",
                    (
                        id,
                        inc["status"],
                        inc["status"],
                        body.actor,
                        f"перенаправлен {inc['team_code']} → {body.team_code}: {reason or ''}",
                        sim_time,
                    ),
                )
            await conn.execute(
                "insert into notifications (run_id, recipient_type, team_code, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, 'team', %s, %s, 'internal', 'team_notice', %s, %s, 'sent', %s, now())",
                (
                    inc["run_id"],
                    body.team_code,
                    id,
                    f"Инцидент {inc['title']} передан вашей команде",
                    reason or "Перенаправлено оператором CX.",
                    sim_time,
                ),
            )
        elif a in ("reply_client", "request_client_data"):
            if not inc["primary_client_id"]:
                raise Problem(422, "У инцидента нет опознанного клиента")
            if not (body.text or "").strip():
                raise Problem(422, "Укажите text")
            text = PII_RE.sub("[скрыто]", body.text or "")
            sig = await fetch_one(
                conn,
                "select signal_id from incident_signals where incident_id = %s order by (link_type = 'primary') desc, linked_sim limit 1",
                (id,),
            )
            await conn.execute(
                "insert into notifications (run_id, recipient_type, client_id, signal_id, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, 'client', %s, %s, %s, %s, %s, %s, %s, 'sent', %s, now())",
                (
                    inc["run_id"],
                    inc["primary_client_id"],
                    (sig or {}).get("signal_id"),
                    id,
                    body.channel_code or "chat",
                    "manual_reply" if a == "reply_client" else "clarify_request",
                    "Ответ сотрудника" if a == "reply_client" else "Нужно уточнение",
                    text,
                    sim_time,
                ),
            )
            if a == "request_client_data" and "awaiting_client" in STATUS_TRANSITIONS.get(str(inc["status"]), set()):
                await _transition(
                    conn, inc, "awaiting_client", body.actor, reason or "запрошены данные у клиента", sim_time
                )
        elif a == "close":
            if inc["status"] not in ("resolved", "closed"):
                await _transition(conn, inc, "resolved", body.actor, reason or "закрыт оператором", sim_time)
            await _transition(conn, inc, "closed", body.actor, reason or "закрыт оператором", sim_time)
            if body.text:
                await conn.execute(
                    "update incidents set resolution_summary = %s, updated_at = now() where id = %s", (body.text, id)
                )
        elif a == "reject":
            await _transition(conn, inc, "rejected", body.actor, reason or "отклонён оператором", sim_time)
            await conn.execute(
                "update incidents set routing_status = 'rejected', updated_at = now() where id = %s", (id,)
            )
        elif a == "mark_duplicate":
            if not body.duplicate_of_id:
                raise Problem(422, "Укажите duplicate_of_id")
            orig = await fetch_one(conn, "select id from incidents where id = %s", (body.duplicate_of_id,))
            if not orig or body.duplicate_of_id == id:
                raise Problem(404, "Исходный инцидент не найден")
            await _transition(
                conn, inc, "duplicate", body.actor, f"дубликат инцидента #{body.duplicate_of_id}", sim_time
            )
            await conn.execute(
                "insert into incident_signals (incident_id, signal_id, link_type, linked_sim) select %s, signal_id, 'duplicate', %s from incident_signals where incident_id = %s on conflict do nothing",
                (body.duplicate_of_id, sim_time, id),
            )
        elif a == "change_priority":
            if body.priority is None:
                raise Problem(422, "Укажите priority 1..4")
            await conn.execute(
                "update incidents set priority = %s, updated_at = now() where id = %s", (body.priority, id)
            )
            await conn.execute(
                "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, %s, %s, 'human', %s, %s, %s)",
                (
                    id,
                    inc["status"],
                    inc["status"],
                    body.actor,
                    f"приоритет {inc['priority']} → {body.priority}: {reason or ''}",
                    sim_time,
                ),
            )
        elif a == "escalate":
            if not reason:
                raise Problem(422, "Укажите reason")
            await conn.execute(
                "insert into escalations (run_id, incident_id, reason, severity, to_role, status, created_by, created_sim) values (%s, %s, %s, 'high', 'cx_lead', 'open', 'human', %s)",
                (inc["run_id"], id, reason, sim_time),
            )
            if "escalated" in STATUS_TRANSITIONS.get(str(inc["status"]), set()):
                await _transition(conn, inc, "escalated", body.actor, reason, sim_time)
            await conn.execute(
                "update incidents set routing_status = 'escalated', updated_at = now() where id = %s", (id,)
            )
        await dcltv.compute_incident(conn, id, sim_time=sim_time)
        brief = await fetch_one(
            conn,
            "select id, public_id, status, team_code, priority, routing_status from incidents where id = %s",
            (id,),
        )
        await conn.execute(
            "select pg_notify('incidents', %s)",
            (
                dumps(
                    {
                        "type": "status",
                        "run_id": inc["run_id"],
                        "data": {**(brief or {}), "action": a, "actor": body.actor},
                    }
                ),
            ),
        )
        if a == "escalate":
            await conn.execute(
                "select pg_notify('escalations', %s)",
                (dumps({"type": "created", "run_id": inc["run_id"], "data": {"incident_id": id}}),),
            )
    return await get_incidents_id(request, id)


@router.get("/api/teams/load", summary="Нагрузка команд и соблюдение SLA (вкладка «Команды»)")
async def get_teams_load(request: Request, run_id: str | None = Query(None)) -> Any:
    """Для каждой команды: открытые / в работе, SLA под угрозой (< 2 ч) и сорванные, обязательные отчёты (должны / пропущены), среднее время взятия, доля закрытых в SLA."""
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        rows = await fetch_all(
            conn,
            f"""
            with st as (select sim_time from sim_state where id = 1),
            inc as (
              select i.*, (select count(*) from unnest(i.report_due_sims) d, st where d <= st.sim_time) as reports_due_n,
                     (select count(*) from unnest(i.report_due_sims) d, st where d <= st.sim_time) - (select count(*) from incident_artifacts a where a.incident_id = i.id and a.kind = 'progress_report') as reports_missing_n
              from incidents i {"where i.run_id = %s" if rid is not None else ""}
            )
            select t.code as team_code, t.name_ru, t.speed_profile, t.lead_display_name,
                   count(*) filter (where inc.status in ('new','classified','routed','awaiting_human','escalated'))::int as open,
                   count(*) filter (where inc.status in ('in_progress','fix_proposed','fix_deployed','verifying','awaiting_client'))::int as in_progress,
                   count(*) filter (where inc.status not in ('resolved','closed','rejected','duplicate') and inc.sla_due_sim >= st.sim_time and inc.sla_due_sim < st.sim_time + interval '2 hours')::int as sla_warning,
                   count(*) filter (where (inc.status not in ('resolved','closed','rejected','duplicate') and inc.sla_due_sim < st.sim_time) or inc.sla_breached)::int as sla_breached,
                   coalesce(sum(inc.reports_due_n) filter (where inc.status not in ('closed','rejected','duplicate')), 0)::int as reports_due,
                   coalesce(sum(greatest(inc.reports_missing_n, 0)) filter (where inc.status not in ('closed','rejected','duplicate')), 0)::int as reports_missing,
                   coalesce(avg(extract(epoch from (inc.taken_sim - inc.created_sim)) / 3600) filter (where inc.taken_sim is not null), 0)::float as avg_take_hours,
                   case when count(*) filter (where inc.status in ('resolved','closed')) = 0 then 100
                        else round(100.0 * count(*) filter (where inc.status in ('resolved','closed') and not inc.sla_breached) / count(*) filter (where inc.status in ('resolved','closed')), 1) end::float as sla_compliance_pct,
                   count(*) filter (where inc.status not in ('resolved','closed','rejected','duplicate') and inc.criticality = 'high')::int as critical_open,
                   count(inc.id)::int as total
            from teams t cross join st left join inc on inc.team_code = t.code
            group by t.code, t.name_ru, t.speed_profile, t.lead_display_name, st.sim_time
            order by open desc, in_progress desc, t.code
            """,
            (rid,) if rid is not None else (),
        )
    return rows
