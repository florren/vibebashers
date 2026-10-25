"""Роутер тега `tasks` (T-079/T-080): задачи сотрудников — подарки, звонки, ручные проверки, напоминания об отчётах; решения approve / change / reject / done."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.economics import dcltv
from app.errors import Problem
from app.sim.events import dumps

router = APIRouter(tags=["tasks"])

TASK_SQL = (
    "select t.id, t.run_id, t.kind, t.incident_id, t.client_id, t.assignee, t.payload, t.status, t.requires_hitl, t.due_sim, t.created_sim, t.resolved_sim, "
    "i.public_id as incident_public_id, i.title as incident_title, i.status as incident_status, i.criticality as incident_criticality, "
    "c.public_id as client_public_id, c.display_name as client_name, c.segment_code as client_segment, c.region_code as client_region, ci.name_ru as client_city, c.churn_risk as client_churn_risk, c.is_active as client_is_active, "
    "g.name_ru as gift_name, "
    "(t.payload->>'when' = 'after_resolved' and i.status in ('resolved','closed')) or (coalesce(t.payload->>'when','now') <> 'after_resolved') as ready, "
    "st.sim_time "
    "from tasks t cross join (select sim_time from sim_state where id = 1) st "
    "left join incidents i on i.id = t.incident_id left join clients c on c.id = t.client_id left join cities ci on ci.id = c.city_id "
    "left join gift_catalog g on g.code = t.payload->'gift'->>'gift_code'"
)
KINDS = ("gift", "callback", "manual_review", "clarify_client", "report_reminder", "closure_review")


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    client = (
        {
            "id": r["client_id"],
            "public_id": r["client_public_id"],
            "display_name": r["client_name"],
            "segment_code": r["client_segment"],
            "region_code": r["client_region"],
            "city_name": r["client_city"],
            "churn_risk": r["client_churn_risk"],
            "is_active": r["client_is_active"],
        }
        if r.get("client_id")
        else None
    )
    out = {k: v for k, v in r.items() if not k.startswith("client_") and k != "sim_time"}
    out["client"] = client
    out["overdue"] = bool(
        r.get("due_sim") and r.get("sim_time") and r["status"] == "open" and r["due_sim"] < r["sim_time"]
    )
    return out


@router.get("/api/tasks", summary="Задачи (подарки, звонки, ручные проверки, напоминания об отчётах)")
async def get_tasks(
    kind: str | None = Query(None),
    status: list[str] | None = Query(None, description="open | approved | changed | rejected | done | cancelled"),
    requires_hitl: bool | None = Query(None),
    ready: bool | None = Query(None, description="true — только готовые к выполнению (инцидент решён или when = now)"),
    run_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(None),
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        if rid is not None:
            where.append("t.run_id = %s")
            args.append(rid)
        if kind:
            where.append("t.kind = %s")
            args.append(kind)
        if status:
            where.append("t.status = any(%s)")
            args.append(status)
        if requires_hitl is not None:
            where.append("t.requires_hitl = %s")
            args.append(requires_hitl)
        if cursor:
            where.append("t.id < %s")
            args.append(int(cursor))
        w = " and ".join(where)
        sql = (
            f"select * from ({TASK_SQL} where {w}) x"
            + (" where x.ready = %s" if ready is not None else "")
            + " order by (x.status = 'open') desc, x.ready desc, x.id desc limit %s"
        )  # noqa: S608
        rows = await fetch_all(conn, sql, (*args, *((ready,) if ready is not None else ()), limit))
        counts = await fetch_all(
            conn,
            f"select t.kind, t.status, count(*) as n from tasks t where {' and '.join(where[:-1] if cursor else where)} group by 1, 2",
            tuple(args[:-1] if cursor else args),
        )  # noqa: S608
    items = [_shape(r) for r in rows]
    return {
        "items": items,
        "next_cursor": str(items[-1]["id"]) if len(items) == limit and items else None,
        "counts": {f"{r['kind']}:{r['status']}": int(r["n"]) for r in counts},
    }


class TaskDecision(BaseModel):
    action: Literal["approve", "change", "reject", "done"]
    payload: dict[str, Any] | None = None
    comment: str | None = Field(None, max_length=1000)
    actor: str = "operator"


def _gift_label(gift: dict[str, Any], gift_name: str | None) -> str:
    if gift.get("gift_code") == "bonus_points" and gift.get("points"):
        return f"{int(gift['points'])} бонусных баллов"
    return gift_name or str(gift.get("privilege_code") or gift.get("gift_code") or "подарок")


@router.post(
    "/api/tasks/{id}", summary="Подтвердить / изменить / отклонить задачу (например, заменить привилегию в подарке)"
)
async def post_tasks_id(id: int, body: TaskDecision) -> Any:  # noqa: A002
    """approve / done у подарка выдают его клиенту (уведомление по шаблону gift_offer); change заменяет подарок и выдаёт новый; reject закрывает без выдачи."""
    async with db() as conn:
        row = await fetch_one(conn, f"{TASK_SQL} where t.id = %s", (id,))  # noqa: S608
        if not row:
            raise Problem(404, "Задача не найдена")
        if row["status"] in ("done", "rejected", "cancelled"):
            raise Problem(409, f"Задача уже закрыта ({row['status']})")
        payload = dict(row["payload"] or {})
        gift_name = row.get("gift_name")
        new_status = {"approve": "approved", "change": "changed", "reject": "rejected", "done": "done"}[body.action]
        if body.action == "change":
            if not body.payload:
                raise Problem(422, "Для change нужен payload (gift_code / points / privilege_code)")
            if row["kind"] == "gift":
                gift = {
                    **(payload.get("gift") or {}),
                    **{k: v for k, v in body.payload.items() if k in ("gift_code", "points", "privilege_code")},
                }
                cat = await fetch_one(
                    conn, "select code, name_ru, segments from gift_catalog where code = %s", (gift.get("gift_code"),)
                )
                if not cat:
                    raise Problem(422, f"Подарок {gift.get('gift_code')!r} не из каталога")
                if row.get("client_segment") and row["client_segment"] not in (cat["segments"] or []):
                    raise Problem(422, f"Подарок {cat['name_ru']} недоступен сегменту {row['client_segment']}")
                gift_name = cat["name_ru"]
                payload["gift"] = gift
            else:
                payload.update(body.payload)
        payload["decision"] = {"action": body.action, "actor": body.actor, "comment": body.comment}
        issued = False
        if (
            row["kind"] == "gift"
            and body.action in ("approve", "change", "done")
            and payload.get("when") == "after_resolved"
            and row.get("incident_status") not in ("resolved", "closed")
        ):
            raise Problem(409, "Подарок можно выдать только после resolved/closed инцидента")
        if row["kind"] == "gift" and body.action in ("approve", "change", "done") and row.get("client_id"):
            gift = payload.get("gift") or {}
            seg = row.get("client_segment")
            tpl = await fetch_one(
                conn,
                "select subject, body from notification_templates where code = 'gift_offer' and lang = 'ru' and (segment_code = %s or segment_code is null) order by segment_code nulls last, (channel_code = 'chat') desc limit 1",
                (seg,),
            )
            label = _gift_label(gift, gift_name)
            text = (tpl or {}).get("body") or "{{ name }}, в знак извинения начислили {{ gift }}."
            text = text.replace("{{ name }}", str(row.get("client_name") or "Уважаемый клиент")).replace(
                "{{ gift }}", label
            )
            text = re.sub(r"\{\{[^}]*\}\}", "", text).strip()
            await conn.execute(
                "insert into notifications (run_id, recipient_type, client_id, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, 'client', %s, %s, 'chat', 'gift_offer', %s, %s, 'sent', %s, now())",
                (
                    row["run_id"],
                    row["client_id"],
                    row["incident_id"],
                    (tpl or {}).get("subject") or "Подарок от банка",
                    text,
                    row["sim_time"],
                ),
            )
            payload["issued"] = {
                "label": label,
                "sim_time": row["sim_time"].isoformat() if row.get("sim_time") else None,
            }
            issued = True
            if row["incident_id"]:
                await conn.execute(
                    "update incidents set flags = array_append(array_remove(coalesce(flags, '{}'), 'gift_issued'), 'gift_issued'), updated_at = now() where id = %s",
                    (row["incident_id"],),
                )
                await dcltv.compute_incident(conn, row["incident_id"], sim_time=row.get("sim_time"))
        final = "done" if (issued and body.action != "change") or body.action == "done" else new_status
        await conn.execute(
            "update tasks set status = %s, payload = %s, resolved_sim = case when %s in ('done','rejected') then %s else resolved_sim end, updated_at = now() where id = %s",
            (final, Jsonb(payload), final, row["sim_time"], id),
        )
        if body.action == "change" and issued:
            await conn.execute(
                "update tasks set status = 'done', resolved_sim = %s where id = %s", (row["sim_time"], id)
            )
        upd = await fetch_one(conn, f"{TASK_SQL} where t.id = %s", (id,))  # noqa: S608
        assert upd is not None
        await conn.execute(
            "select pg_notify('tasks', %s)",
            (
                dumps(
                    {
                        "type": "updated",
                        "run_id": row["run_id"],
                        "data": {"task_id": id, "kind": row["kind"], "status": upd["status"], "action": body.action},
                    }
                ),
            ),
        )
    return _shape(upd)
