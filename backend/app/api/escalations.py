"""Роутер тега `escalations` (T-213/T-214): очередь эскалаций руководителю (ДТЗ FR-3.4), ручная эскалация, подтверждение/закрытие."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.agent import build_decision_chain
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.api.tickets import TICKET_SQL
from app.errors import Problem
from app.sim.events import dumps

router = APIRouter(tags=["escalations"])

ESC_SQL = (
    "select e.id, e.public_id, e.run_id, e.incident_id, i.public_id as ticket_id, e.signal_id, e.reason, e.severity, e.to_role, e.status, e.created_by, "
    "e.agent_run_id, e.human_decision_id, e.acknowledged_by, e.acknowledged_at, e.resolution_ru, e.created_sim, e.created_at, e.updated_at, "
    "i.title as incident_title, i.status as incident_status, i.team_code, i.criticality, c.display_name as client_name, c.segment_code as client_segment, s.channel_code as channel "
    "from escalations e left join incidents i on i.id = e.incident_id left join clients c on c.id = i.primary_client_id left join signals s on s.id = e.signal_id"
)


async def _notify(conn: Any, run_id: int | None, type_: str, data: dict[str, Any]) -> None:
    await conn.execute("select pg_notify('escalations', %s)", (dumps({"type": type_, "run_id": run_id, "data": data}),))


@router.get("/api/escalations", summary="[ДТЗ FR-3.4] Очередь эскалаций руководителю")
async def get_escalations(
    status: list[str] | None = Query(None, description="open | acknowledged | resolved | dismissed"),
    to_role: str | None = Query(None),
    severity: str | None = Query(None),
    run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        if rid is not None:
            where.append("e.run_id = %s")
            args.append(rid)
        if status:
            where.append("e.status = any(%s)")
            args.append(status)
        for expr, val in (("e.to_role = %s", to_role), ("e.severity = %s", severity)):
            if val:
                where.append(expr)
                args.append(val)
        if cursor:
            where.append("e.id < %s")
            args.append(int(cursor))
        w = " and ".join(where)
        rows = await fetch_all(
            conn,
            f"{ESC_SQL} where {w} order by (e.status = 'open') desc, array_position(array['critical','high','medium','low'], e.severity), e.id desc limit %s",  # noqa: S608
            (*args, limit),
        )
        counts = await fetch_all(
            conn,
            f"select e.status, count(*) as n from escalations e where {' and '.join(where[:-1] if cursor else where)} group by 1",
            tuple(args[:-1] if cursor else args),
        )  # noqa: S608
    return {
        "items": rows,
        "next_cursor": str(rows[-1]["id"]) if len(rows) == limit and rows else None,
        "counts": {r["status"]: int(r["n"]) for r in counts},
    }


class EscalationBody(BaseModel):
    incident_id: int | None = None
    signal_id: int | None = None
    reason: str = Field(min_length=3, max_length=1000)
    severity: Literal["low", "medium", "high", "critical"]
    to_role: Literal["cx_lead", "branch_manager"] = "cx_lead"
    actor: str = "operator"


@router.post("/api/escalations", status_code=201, summary="Ручная эскалация оператором (created_by = human)")
async def post_escalations(body: EscalationBody) -> Any:
    if body.incident_id is None and body.signal_id is None:
        raise Problem(422, "Нужен incident_id или signal_id")
    async with db() as conn:
        inc = (
            await fetch_one(conn, "select id, run_id, status from incidents where id = %s", (body.incident_id,))
            if body.incident_id
            else None
        )
        if body.incident_id and not inc:
            raise Problem(404, "Инцидент не найден")
        sig = (
            await fetch_one(conn, "select id, run_id from signals where id = %s", (body.signal_id,))
            if body.signal_id
            else None
        )
        if body.signal_id and not sig:
            raise Problem(404, "Сигнал не найден")
        run_id = (inc or sig or {}).get("run_id")
        now = await fetch_one(conn, "select sim_time from sim_state where id = 1")
        sim_time = (now or {}).get("sim_time") or dt.datetime.now(dt.UTC)
        row = await fetch_one(
            conn,
            "insert into escalations (run_id, incident_id, signal_id, reason, severity, to_role, status, created_by, created_sim) values (%s, %s, %s, %s, %s, %s, 'open', 'human', %s) returning id",
            (run_id, body.incident_id, body.signal_id, body.reason, body.severity, body.to_role, sim_time),
        )
        assert row is not None
        if inc:
            from app.agent.tools.write import STATUS_TRANSITIONS

            if "escalated" in STATUS_TRANSITIONS.get(str(inc["status"]), set()):
                await conn.execute(
                    "update incidents set status = 'escalated', routing_status = 'escalated', updated_at = now() where id = %s",
                    (inc["id"],),
                )
                await conn.execute(
                    "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, %s, 'escalated', 'human', %s, %s, %s)",
                    (inc["id"], inc["status"], body.actor, body.reason, sim_time),
                )
            else:
                await conn.execute(
                    "update incidents set routing_status = 'escalated', updated_at = now() where id = %s", (inc["id"],)
                )
        esc = await fetch_one(conn, f"{ESC_SQL} where e.id = %s", (row["id"],))  # noqa: S608
        assert esc is not None
        await _notify(
            conn,
            run_id,
            "created",
            {
                "escalation_id": esc["id"],
                "public_id": esc["public_id"],
                "incident_id": esc["incident_id"],
                "severity": esc["severity"],
                "to_role": esc["to_role"],
            },
        )
    return esc


@router.get("/api/escalations/{id}", summary="Эскалация с контекстом (сигнал, тикет, цепочка решений)")
async def get_escalations_id(id: int) -> Any:  # noqa: A002
    async with db() as conn:
        esc = await fetch_one(conn, f"{ESC_SQL} where e.id = %s", (id,))  # noqa: S608
        if not esc:
            raise Problem(404, "Эскалация не найдена")
        signal = (
            await fetch_one(
                conn,
                "select id, public_id, channel_code, text, received_sim, status, origin, sentiment, client_id, classification from signals where id = %s",
                (esc["signal_id"],),
            )
            if esc["signal_id"]
            else None
        )
        ticket = (
            await fetch_one(conn, f"{TICKET_SQL} where t.incident_id = %s", (esc["incident_id"],))
            if esc["incident_id"]
            else None
        )  # noqa: S608
        decision = (
            await fetch_one(
                conn,
                "select id, decision, requested_at, decided_sim, decided_by, comment, agent_proposal from human_decisions where id = %s",
                (esc["human_decision_id"],),
            )
            if esc["human_decision_id"]
            else None
        )
        chain = await build_decision_chain(conn, int(esc["agent_run_id"])) if esc["agent_run_id"] else None
    return {**esc, "signal": signal, "ticket": ticket, "human_decision": decision, "decision_chain": chain}


class AckBody(BaseModel):
    status: Literal["acknowledged", "resolved", "dismissed"]
    resolution_ru: str | None = Field(None, max_length=1000)
    actor: str = "cx_lead"


@router.post("/api/escalations/{id}/ack", summary="Руководитель подтвердил / закрыл / отклонил эскалацию")
async def post_escalations_id_ack(id: int, body: AckBody) -> Any:  # noqa: A002
    async with db() as conn:
        cur = await fetch_one(conn, "select id, run_id, status, incident_id from escalations where id = %s", (id,))
        if not cur:
            raise Problem(404, "Эскалация не найдена")
        if cur["status"] in ("resolved", "dismissed"):
            raise Problem(409, f"Эскалация уже закрыта ({cur['status']})")
        if body.status in ("resolved", "dismissed") and not (body.resolution_ru or "").strip():
            raise Problem(422, "Укажите резолюцию (resolution_ru)")
        await conn.execute(
            "update escalations set status = %s, acknowledged_by = coalesce(acknowledged_by, %s), acknowledged_at = coalesce(acknowledged_at, now()), resolution_ru = coalesce(%s, resolution_ru), updated_at = now() where id = %s",
            (body.status, body.actor, body.resolution_ru, id),
        )
        if body.status in ("resolved", "dismissed") and cur["incident_id"]:
            still = await fetch_one(
                conn,
                "select count(*) as n from escalations where incident_id = %s and status in ('open','acknowledged')",
                (cur["incident_id"],),
            )
            if int((still or {}).get("n") or 0) == 0:
                inc = await fetch_one(
                    conn, "select status, team_code from incidents where id = %s", (cur["incident_id"],)
                )
                if inc and inc["status"] == "escalated":
                    now = await fetch_one(conn, "select sim_time from sim_state where id = 1")
                    await conn.execute(
                        "update incidents set status = 'in_progress', routing_status = 'routed', taken_sim = coalesce(taken_sim, %s), updated_at = now() where id = %s",
                        ((now or {}).get("sim_time"), cur["incident_id"]),
                    )
                    await conn.execute(
                        "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, 'escalated', 'in_progress', 'human', %s, %s, %s)",
                        (
                            cur["incident_id"],
                            body.actor,
                            f"эскалация {body.status}: {body.resolution_ru}",
                            (now or {}).get("sim_time"),
                        ),
                    )
                else:
                    await conn.execute(
                        "update incidents set routing_status = 'routed', updated_at = now() where id = %s and routing_status = 'escalated'",
                        (cur["incident_id"],),
                    )
        esc = await fetch_one(conn, f"{ESC_SQL} where e.id = %s", (id,))  # noqa: S608
        assert esc is not None
        await _notify(
            conn,
            cur["run_id"],
            body.status,
            {
                "escalation_id": id,
                "public_id": esc["public_id"],
                "incident_id": esc["incident_id"],
                "status": body.status,
            },
        )
    return esc
