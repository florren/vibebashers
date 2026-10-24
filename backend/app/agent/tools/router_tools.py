"""Фасады роутера (ТЗ 9.2, ДТЗ FR-3): сигнатуры router_tools.schema.json поверх внутренних инструментов.

Аргументы tool_call — только поля схемы. signal_id, client_id и инцидент берутся из кадра ToolContext.act_frame.
Каждый успешный фасад оставляет один tool_call: внутренние имена — в wraps.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.agent import policies as pol
from app.agent.tools.base import ActFrame, ToolContext, ToolError, tool
from app.agent.tools.write import PII_RE
from app.agent.tools.write import create_incident as write_create_incident
from app.agent.tools.write import escalate_to_manager as write_escalate_to_manager
from app.agent.tools.write import link_signal_to_incident as write_link_signal
from app.agent.tools.write import notify_client as write_notify_client
from app.agent.tools.write import notify_team as write_notify_team
from app.agent.tools.write import request_human_decision as write_request_human
from app.agent.tools.write import schedule_followup as write_schedule_followup
from app.agent.tools.write import update_incident as write_update_incident
from app.sim.events import dumps

_ROLE_TEAM = {"cx_lead": "team_cx", "branch_manager": "team_branch_network"}
_SEVERITY = {"low", "medium", "high", "critical"}


def _frame(ctx: ToolContext) -> ActFrame:
    if ctx.act_frame is None:
        raise ToolError("фасад роутера вызван без кадра act")
    return ctx.act_frame


def _note(ctx: ToolContext, name: str) -> None:
    ctx.pending_wraps.append(name)


async def _known_team(ctx: ToolContext, department: str) -> None:
    row = await ctx.fetchone("select code from teams where code = %s", (department,))
    if row is None:
        raise ToolError(f"неизвестная команда: {department}")


def _check_summary(summary: str) -> str:
    text = summary.strip()
    if not 10 <= len(text) <= 300:
        raise ToolError("summary: ожидается строка от 10 до 300 символов")
    return text


async def _bind_ticket(
    ctx: ToolContext,
    *,
    department: str,
    priority: int,
    summary: str,
    routing_status: str,
    create: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """Открытый инцидент или дедупликация act → link; иначе create, если кадр это разрешает."""
    frame = _frame(ctx)
    target = frame.incident_id or frame.link_incident_id
    if target:
        _note(ctx, "link_signal_to_incident")
        brief = await write_link_signal(ctx, frame.signal_id, int(target))
        linked = True
    elif create:
        spec = dict(frame.spec or {})
        spec["team"] = department
        spec["priority"] = priority
        spec["title_ru"] = summary[:120]
        problem = dict(spec.get("problem_summary") or {})
        problem["problem"] = summary[:300]
        spec["problem_summary"] = problem
        _note(ctx, "create_incident")
        brief = await write_create_incident(ctx, frame.signal_id, frame.client_id, spec)
        linked = False
    else:
        return None, False
    incident_id = int(brief["incident_id"])
    frame.incident_id = incident_id
    status = str(brief.get("status") or "")
    public_id = brief.get("public_id")
    if not status:
        row = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
        status = str(row[0]) if row else "routed"
    _note(ctx, "update_incident")
    brief = await write_update_incident(
        ctx,
        incident_id,
        status,
        None,
        {"routing_status": routing_status, "priority": priority, "team_code": department},
    )
    if public_id and not brief.get("public_id"):
        brief = {**brief, "public_id": public_id}
    await ctx.conn.execute(
        "update incidents set title = %s, problem_summary = coalesce(problem_summary, '{}'::jsonb) || %s::jsonb "
        "where id = %s",
        (summary[:120], dumps({"problem": summary[:300]}), incident_id),
    )
    return brief, linked


@tool("route_to_department")
async def route_to_department(ctx: ToolContext, department: str, priority: int, summary: str) -> dict[str, Any]:
    """Маршрут в команду: новый тикет или связь с уже открытым. ticket_id = public_id, routing_status=routed."""
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 4:
        raise ToolError("priority: целое от 1 до 4")
    text = _check_summary(summary)
    await _known_team(ctx, department)
    frame = _frame(ctx)
    # Открытый инцидент и дедупликация act уже лежат в кадре — тогда link, иначе create.
    has_target = bool(frame.incident_id or frame.link_incident_id)
    create = not has_target and (frame.spec or {}).get("incident_action", "create") != "none"
    brief, linked = await _bind_ticket(
        ctx, department=department, priority=priority, summary=text, routing_status="routed", create=create
    )
    if brief is None:
        raise ToolError("нет инцидента для маршрута")
    return {
        "ticket_id": brief.get("public_id"),
        "incident_id": int(brief["incident_id"]),
        "linked": linked,
        "department": department,
    }


@tool("notify_customer")
async def notify_customer(ctx: ToolContext, channel: str, message: str) -> dict[str, Any]:
    """Текст клиенту без нового шаблона: те же запрещённые фразы и маскирование ПДн, что у notify_client."""
    text = message.strip()
    if not 10 <= len(text) <= 1000:
        raise ToolError("message: ожидается строка от 10 до 1000 символов")
    bad = pol.forbidden_phrases(text)
    if bad:
        raise ToolError("запрещённая формулировка: " + ", ".join(bad))
    frame = _frame(ctx)
    body = PII_RE.sub("****", text)
    _note(ctx, "notify_client")
    data = await write_notify_client(
        ctx,
        frame.client_id,
        frame.signal_id,
        frame.incident_id,
        channel,
        "ack_received",
        {},
        text_override=body,
    )
    return {"notification_id": data["notification_id"], "delivery": "emulated"}


@tool("escalate_to_manager")
async def escalate_to_manager(ctx: ToolContext, reason: str, severity: str, to_role: str = "cx_lead") -> dict[str, Any]:
    """Эскалация поверх тикета: запись escalations, уведомление роли и HITL без перехода в awaiting_human."""
    text = reason.strip()
    if not 5 <= len(text) <= 300:
        raise ToolError("reason: ожидается строка от 5 до 300 символов")
    if severity not in _SEVERITY:
        raise ToolError(f"неизвестная критичность: {severity}")
    if to_role not in _ROLE_TEAM:
        raise ToolError(f"неизвестная роль эскалации: {to_role}")
    frame = _frame(ctx)
    incident_id = frame.incident_id
    if incident_id is None:
        raise ToolError("эскалация без тикета")
    _note(ctx, "escalate_to_manager")
    esc = await write_escalate_to_manager(ctx, frame.signal_id, incident_id, text, severity, to_role)
    team = _ROLE_TEAM[to_role]
    _note(ctx, "notify_team")
    await write_notify_team(
        ctx,
        team,
        int(incident_id),
        frame.signal_id,
        text,
        {"incident_id": incident_id, "title": text[:120], "criticality": severity},
    )
    # incident_id не передаём: awaiting_human из escalated в FSM запрещён.
    _note(ctx, "request_human_decision")
    hitl = await write_request_human(
        ctx,
        frame.signal_id,
        None,
        text,
        {
            "kind": "escalation",
            "escalation_id": esc.get("escalation_id"),
            "public_id": esc.get("public_id"),
            "severity": severity,
            "to_role": to_role,
        },
        pol.human_options("policy_other"),
        pol.human_recommendation("policy_other"),
    )
    hid = hitl.get("human_decision_id")
    if hid is not None and esc.get("escalation_id") is not None:
        await ctx.conn.execute(
            "update escalations set human_decision_id = %s where id = %s",
            (hid, int(esc["escalation_id"])),
        )
        if incident_id is not None:
            await ctx.conn.execute(
                "update human_decisions set incident_id = %s where id = %s and incident_id is null",
                (incident_id, hid),
            )
    return {
        "escalation_id": esc.get("escalation_id"),
        "public_id": esc.get("public_id"),
        "hitl_item_id": int(hid) if hid is not None else None,
    }


@tool("request_clarification")
async def request_clarification(ctx: ToolContext, question: str, channel: str) -> dict[str, Any]:
    """Один вопрос клиенту и follow-up awaiting_client. route_to_department не вызывается.

    routing_status=clarification ставится после create/link: create_incident с командой сам пишет routed.
    """
    text = question.strip()
    if not 5 <= len(text) <= 400:
        raise ToolError("question: ожидается строка от 5 до 400 символов")
    bad = pol.forbidden_phrases(text)
    if bad:
        raise ToolError("запрещённая формулировка: " + ", ".join(bad))
    frame = _frame(ctx)
    spec = frame.spec or {}
    department = str(spec.get("team") or "team_cx")
    await _known_team(ctx, department)
    priority = int(spec.get("priority") or 3)
    summary = _check_summary(str(spec.get("title_ru") or text))
    allow_create = spec.get("incident_action", "create") == "create" or bool(
        frame.incident_id or frame.link_incident_id
    )
    brief, _linked = await _bind_ticket(
        ctx,
        department=department,
        priority=priority,
        summary=summary,
        routing_status="clarification",
        create=allow_create and not (frame.incident_id or frame.link_incident_id),
    )
    incident_id = int(brief["incident_id"]) if brief else frame.incident_id
    body = PII_RE.sub("****", text)
    _note(ctx, "notify_client")
    data = await write_notify_client(
        ctx,
        frame.client_id,
        frame.signal_id,
        incident_id,
        channel,
        "clarify_request",
        {},
        text_override=body,
    )
    hours = float(spec.get("followup_hours") or 4.0)
    _note(ctx, "schedule_followup")
    follow = await write_schedule_followup(
        ctx,
        frame.signal_id,
        incident_id,
        hours,
        "awaiting_client",
        {"incident_id": incident_id},
    )
    wake = follow.get("wake_sim") or (ctx.sim_time + dt.timedelta(hours=hours))
    return {"notification_id": data["notification_id"], "followup_at_sim": wake}
