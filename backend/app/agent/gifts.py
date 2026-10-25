"""Выбор подарка и автовыдача mass после resolved (T-078, ТЗ 8.5)."""

from __future__ import annotations

import re
from typing import Any

from psycopg.types.json import Jsonb

from app.agent import policies as pol
from app.agent.tools.base import ToolContext
from app.economics import dcltv


def choose(
    segment: str | None,
    criticality: str,
    flags: list[str],
    psychotype: str | None = None,
) -> dict[str, Any] | None:
    """Поля decision.gift: баллы, привилегия, when, requires_hitl."""
    crit = criticality if criticality in ("low", "medium", "high") else "medium"
    points = {"low": 300, "medium": 600, "high": 1000}.get(crit, 600)
    if "repeat" in flags:
        points = min(1000, points + 200)
    if psychotype == "bonus_hunter":
        points = 1000

    gift: dict[str, Any] = {"gift_code": "bonus_points", "points": points, "privilege_code": None}
    if segment == "vip":
        if crit == "high" and "churn_intent" in flags:
            gift["privilege_code"] = "business_class_discount"
        elif crit == "high" or "churn_intent" in flags:
            gift["privilege_code"] = "restaurant_special"
        elif crit == "medium":
            gift["privilege_code"] = "lounge_pass"
    if psychotype == "status_oriented" and segment in ("vip", "ultra_vip") and not gift.get("privilege_code"):
        gift["privilege_code"] = "lounge_pass"

    privilege = gift.get("privilege_code")
    requires_hitl = privilege in pol.PARTNER_PRIVILEGES or segment == "ultra_vip"
    return {
        **gift,
        "when": "after_resolved",
        "requires_hitl": requires_hitl,
    }


def should_auto_issue(
    *,
    requires_hitl: bool,
    when: str | None,
    incident_status: str,
) -> bool:
    if requires_hitl:
        return False
    if (when or "after_resolved") != "after_resolved":
        return False
    return incident_status in ("resolved", "closed")


def _gift_label(gift: dict[str, Any], gift_name: str | None) -> str:
    if gift.get("gift_code") == "bonus_points" and gift.get("points"):
        return f"{int(gift['points'])} бонусных баллов"
    return gift_name or str(gift.get("privilege_code") or gift.get("gift_code") or "подарок")


async def _issue_gift_task_row(conn: Any, row: dict[str, Any]) -> bool:
    """Выдача одной задачи gift: уведомление gift_offer, gift_issued, status=done. False если уже выдано."""
    payload = dict(row.get("payload") or {})
    if payload.get("issued"):
        return False
    gift = payload.get("gift") or {}
    if not row.get("client_id"):
        return False
    seg = row.get("client_segment")
    tpl = await conn.execute(
        "select subject, body from notification_templates where code = 'gift_offer' and lang = 'ru' and (segment_code = %s or segment_code is null) order by segment_code nulls last, (channel_code = 'chat') desc limit 1",
        (seg,),
    )
    tpl_row = await tpl.fetchone()
    subject = tpl_row[0] if tpl_row else "Подарок от банка"
    body_tpl = tpl_row[1] if tpl_row else "{{ name }}, в знак извинения начислили {{ gift }}."
    label = _gift_label(gift, row.get("gift_name"))
    text = body_tpl.replace("{{ name }}", str(row.get("client_name") or "Уважаемый клиент")).replace(
        "{{ gift }}", label
    )
    text = re.sub(r"\{\{[^}]*\}\}", "", text).strip()
    sim_time = row.get("sim_time")
    await conn.execute(
        "insert into notifications (run_id, recipient_type, client_id, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, 'client', %s, %s, 'chat', 'gift_offer', %s, %s, 'sent', %s, now())",
        (
            row["run_id"],
            row["client_id"],
            row["incident_id"],
            subject,
            text,
            sim_time,
        ),
    )
    payload["issued"] = {
        "label": label,
        "sim_time": sim_time.isoformat() if sim_time else None,
    }
    if row.get("incident_id"):
        await conn.execute(
            "update incidents set flags = array_append(array_remove(coalesce(flags, '{}'), 'gift_issued'), 'gift_issued'), updated_at = now() where id = %s",
            (row["incident_id"],),
        )
    await conn.execute(
        "update tasks set status = 'done', payload = %s, resolved_sim = %s, updated_at = now() where id = %s",
        (Jsonb(payload), sim_time, row["task_id"]),
    )
    return True


async def issue_automatic(ctx: ToolContext, incident_id: int) -> int:
    """Автовыдача открытых gift-задач без HITL после resolved/closed; идемпотентно."""
    cur = await ctx.conn.execute(
        """
        select t.id as task_id, t.run_id, t.payload, t.requires_hitl, t.client_id, t.incident_id,
               c.segment_code as client_segment, c.display_name as client_name,
               i.status as incident_status,
               g.name_ru as gift_name,
               (select sim_time from sim_state where id = 1) as sim_time
        from tasks t
        join incidents i on i.id = t.incident_id
        left join clients c on c.id = t.client_id
        left join gift_catalog g on g.code = t.payload->'gift'->>'gift_code'
        where t.incident_id = %s and t.kind = 'gift' and t.status = 'open' and t.run_id = %s
        """,
        (incident_id, ctx.run_id),
    )
    rows = await cur.fetchall()
    cols = [d.name for d in cur.description] if cur.description else []
    issued = 0
    for raw in rows:
        row = dict(zip(cols, raw, strict=True))
        payload = row.get("payload") or {}
        when = payload.get("when") if isinstance(payload, dict) else None
        if not should_auto_issue(
            requires_hitl=bool(row.get("requires_hitl")),
            when=when,
            incident_status=str(row.get("incident_status") or ""),
        ):
            continue
        if await _issue_gift_task_row(ctx.conn, row):
            issued += 1
    if issued:
        await dcltv.compute_incident(ctx.conn, incident_id, sim_time=ctx.sim_time)
    return issued
