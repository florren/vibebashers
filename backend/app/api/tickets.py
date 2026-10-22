"""Роутер тега `tickets` (T-214): тикетница ДТЗ FR-3.2 — представление `v_tickets` над инцидентами, детали с эскалациями и цепочкой решений."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.api.agent import build_decision_chain
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.api.incidents import INCIDENT_SQL
from app.errors import Problem

router = APIRouter(tags=["tickets"])

TICKET_SQL = (
    "select t.ticket_id, t.incident_id, t.run_id, t.department, t.priority, t.summary, t.severity, t.status, t.incident_status, t.routing_status, "
    "t.channel, t.sentiment, t.client_segment, t.region_code, t.created_at, t.escalated, t.agent_run_id, "
    "i.criticality, i.incident_type, i.sla_due_sim, i.sla_breached, i.primary_client_id, c.display_name as client_name, "
    "(select count(*) from escalations e where e.incident_id = t.incident_id) as escalations_count "
    "from v_tickets t join incidents i on i.id = t.incident_id left join clients c on c.id = i.primary_client_id"
)


@router.get("/api/tickets", summary="[ДТЗ FR-3.2] Тикетница: представление v_tickets над инцидентами в терминах ДТЗ")
async def get_tickets(
    status: list[str] | None = Query(None, description="open | in_progress | resolved | closed | rejected"),
    department: str | None = Query(None),
    priority: int | None = Query(None, ge=1, le=4),
    escalated: bool | None = Query(None),
    routing_status: str | None = Query(None),
    q: str | None = Query(None, description="поиск по номеру тикета и сводке"),
    run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        if rid is not None:
            where.append("t.run_id = %s")
            args.append(rid)
        if status:
            where.append("t.status = any(%s)")
            args.append(status)
        for expr, val in (
            ("t.department = %s", department),
            ("t.priority = %s", priority),
            ("t.escalated = %s", escalated),
            ("t.routing_status = %s", routing_status),
        ):
            if val is not None:
                where.append(expr)
                args.append(val)
        if q:
            where.append("(t.ticket_id ilike %s or t.summary ilike %s)")
            args += [f"%{q}%", f"%{q}%"]
        if cursor:
            where.append("t.incident_id < %s")
            args.append(int(cursor))
        w = " and ".join(where)
        total = await fetch_one(conn, f"select count(*) as n from ({TICKET_SQL} where {w}) x", tuple(args))  # noqa: S608 — условия параметризованы
        rows = await fetch_all(conn, f"{TICKET_SQL} where {w} order by t.incident_id desc limit %s", (*args, limit))  # noqa: S608
    return {
        "items": rows,
        "next_cursor": str(rows[-1]["incident_id"]) if len(rows) == limit and rows else None,
        "total": int((total or {}).get("n") or 0),
    }


@router.get("/api/tickets/{ticket_id}", summary="Тикет с цепочкой решений агента и эскалациями")
async def get_tickets_ticket_id(request: Request, ticket_id: str) -> Any:
    async with db() as conn:
        key = "t.incident_id = %s" if ticket_id.isdigit() else "t.ticket_id = %s"
        row = await fetch_one(
            conn, f"{TICKET_SQL} where {key}", (int(ticket_id) if ticket_id.isdigit() else ticket_id,)
        )  # noqa: S608
        if not row:
            raise Problem(404, "Тикет не найден")
        incident = await fetch_one(conn, f"{INCIDENT_SQL} where i.id = %s", (row["incident_id"],))  # noqa: S608
        escalations = await fetch_all(
            conn,
            "select e.*, i.public_id as ticket_id from escalations e left join incidents i on i.id = e.incident_id where e.incident_id = %s order by e.id desc",
            (row["incident_id"],),
        )
        history = await fetch_all(
            conn,
            "select id, from_status, to_status, actor_type, actor_ref, reason, changed_sim from incident_status_history where incident_id = %s order by id",
            (row["incident_id"],),
        )
        chain = await build_decision_chain(conn, int(row["agent_run_id"])) if row.get("agent_run_id") else None
    return {**row, "incident": incident, "escalations": escalations, "history": history, "decision_chain": chain}
