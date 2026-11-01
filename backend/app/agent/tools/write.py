"""Инструменты записи (T-058): инциденты (FSM статусов, SLA, история), связи, уведомления по шаблонам, задачи, HITL, follow-up.
Идемпотентность — по (agent_run_id, вид действия); все строки с run_id; NOTIFY для WS."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from app.agent import gifts as agent_gifts
from app.agent.tools.base import ToolContext, ToolError, mask_name, tool
from app.sim.events import dumps

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "new": {"classified", "routed", "awaiting_human", "rejected", "duplicate", "escalated"},
    "classified": {"routed", "awaiting_human", "awaiting_client", "rejected", "duplicate", "escalated"},
    "routed": {"in_progress", "awaiting_human", "awaiting_client", "escalated", "duplicate", "resolved"},
    "in_progress": {"fix_proposed", "fix_deployed", "awaiting_client", "awaiting_human", "escalated", "resolved"},
    "fix_proposed": {"fix_deployed", "in_progress", "awaiting_human"},
    "fix_deployed": {"verifying", "resolved", "in_progress"},
    "verifying": {"resolved", "in_progress"},
    "resolved": {"closed", "in_progress"},
    "awaiting_human": {"classified", "routed", "in_progress", "rejected", "escalated", "closed"},
    "awaiting_client": {"classified", "routed", "in_progress", "closed"},
    "escalated": {"in_progress", "routed", "resolved", "closed"},
    "closed": set(),
    "duplicate": set(),
    "rejected": set(),
}
PII_RE = re.compile(r"\b\d{16}\b|\b\d{4} \d{4} \d{4} \d{4}\b|\+7\d{10}\b")


async def _history(
    ctx: ToolContext,
    incident_id: int,
    from_status: str | None,
    to_status: str,
    reason: str | None,
    actor: str = "agent",
) -> None:
    await ctx.conn.execute(
        "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, %s, %s, %s, %s, %s, %s)",
        (incident_id, from_status, to_status, actor, str(ctx.agent_run_id), reason, ctx.sim_time),
    )


async def _incident_brief(ctx: ToolContext, incident_id: int) -> dict[str, Any]:
    row = await ctx.fetchone(
        "select id, public_id, title, status, team_code, criticality, priority, sla_due_sim, mass_impact, incident_type from incidents where id = %s",
        (incident_id,),
    )
    if not row:
        raise ToolError(f"инцидент {incident_id} не найден")
    return {
        "incident_id": row[0],
        "public_id": row[1],
        "title": row[2],
        "status": row[3],
        "team": row[4],
        "criticality": row[5],
        "priority": row[6],
        "sla_due_sim": row[7],
        "mass_impact": row[8],
        "incident_type": row[9],
    }


@tool("create_incident")
async def create_incident(
    ctx: ToolContext, signal_id: int, client_id: int | None, spec: dict[str, Any]
) -> dict[str, Any]:
    """Создать инцидент (идемпотентно для agent_run_id): spec = поля decision + classification (см. nodes.act)."""
    existing = await ctx.fetchone("select id from incidents where agent_run_id = %s", (ctx.agent_run_id,))
    if existing:
        return await _incident_brief(ctx, int(existing[0]))
    sla = spec.get("sla") or {}
    row = await ctx.fetchone(
        "insert into incidents (run_id, title, incident_type, product_code, system_code, error_code, team_code, co_team_codes, complexity, criticality, priority, status, flags, mass_impact, region_code, primary_client_id, fault_id, created_by, created_sim, sla_due_sim, take_due_sim, report_due_sims, agent_run_id, routing_status, problem_summary) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new', %s, %s, %s, %s, %s, 'agent', %s, %s, %s, %s, %s, 'pending', %s::jsonb) returning id",
        (
            ctx.run_id,
            (spec.get("title_ru") or "Обращение клиента")[:120],
            spec.get("incident_type") or "tech_fault",
            spec.get("product"),
            spec.get("system"),
            spec.get("error_code"),
            spec.get("team"),
            list(spec.get("co_teams") or []),
            spec.get("complexity") or "medium",
            spec.get("criticality") or "medium",
            int(spec.get("priority") or 3),
            list(spec.get("flags") or []),
            int(spec.get("mass_impact") or 1),
            spec.get("region_code"),
            client_id,
            spec.get("fault_id"),
            ctx.sim_time,
            sla.get("due_sim"),
            sla.get("take_due_sim"),
            list(sla.get("report_due_sims") or []),
            ctx.agent_run_id,
            dumps(spec.get("problem_summary") or {}),
        ),
    )
    incident_id = int(row[0])  # type: ignore[index]
    await ctx.conn.execute(
        "insert into incident_signals (incident_id, signal_id, link_type, linked_sim) values (%s, %s, 'primary', %s) on conflict do nothing",
        (incident_id, signal_id, ctx.sim_time),
    )
    # T-108: audit отражает связь первичного сигнала до первой записи истории.
    await _history(ctx, incident_id, None, "new", "создан агентом")
    await update_incident(ctx, incident_id, "classified", "классификация агента")
    if spec.get("team"):
        await update_incident(ctx, incident_id, "routed", f"маршрут → {spec['team']}")
        await ctx.conn.execute("update incidents set routing_status = 'routed' where id = %s", (incident_id,))
    brief = await _incident_brief(ctx, incident_id)
    await ctx.notify("incidents", "created", brief)
    return brief


@tool("link_signal_to_incident")
async def link_signal_to_incident(
    ctx: ToolContext, signal_id: int, incident_id: int, link_type: str = "linked"
) -> dict[str, Any]:
    await ctx.conn.execute(
        "insert into incident_signals (incident_id, signal_id, link_type, linked_sim) values (%s, %s, %s, %s) on conflict do nothing",
        (incident_id, signal_id, link_type, ctx.sim_time),
    )
    await ctx.conn.execute(
        "update incidents set mass_impact = (select count(distinct coalesce(s.client_id, -s.id)) from incident_signals isg join signals s on s.id = isg.signal_id where isg.incident_id = incidents.id), "
        "flags = case when (select count(distinct coalesce(s.client_id, -s.id)) from incident_signals isg join signals s on s.id = isg.signal_id where isg.incident_id = incidents.id) >= 3 and not ('mass_impact' = any(flags)) then array_append(flags, 'mass_impact') else flags end, updated_at = now() where id = %s",
        (incident_id,),
    )
    brief = await _incident_brief(ctx, incident_id)
    await ctx.notify("incidents", "updated", brief)
    return brief


async def resume_approved_incident(
    ctx: ToolContext, incident_id: int, approval_agent_run_id: int | None = None
) -> dict[str, Any]:
    """Снять только уже согласованное ожидание; другой незавершённый HITL сохраняет блокировку."""
    row = await ctx.fetchone(
        "select status from incidents where id=%s and run_id=%s for update", (incident_id, ctx.run_id)
    )
    if not row or row[0] != "awaiting_human":
        return {"resumed": False, "reason": "not_awaiting_human"}
    approved = await ctx.fetchone(
        "select id,decision from human_decisions where agent_run_id=%s and incident_id=%s and decision is not null order by id desc limit 1",
        (approval_agent_run_id or ctx.agent_run_id, incident_id),
    )
    if not approved or approved[1] not in ("accept", "modify"):
        return {"resumed": False, "reason": "no_approval"}
    pending = await ctx.fetchone(
        "select h.id from human_decisions h where h.decision is null and "
        "(h.incident_id=%s or exists(select 1 from incident_signals x where x.incident_id=%s and x.signal_id=h.signal_id)) limit 1",
        (incident_id, incident_id),
    )
    if pending:
        return {"resumed": False, "reason": "pending_human_decision"}
    brief = await update_incident(
        ctx, incident_id, "routed", f"HITL {approved[0]} согласован: передача команде", {"routing_status": "routed"}
    )
    return {**brief, "resumed": True, "human_decision_id": approved[0]}


@tool("update_incident")
async def update_incident(
    ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Смена статуса по FSM ТЗ 8.3 (недопустимый переход — ToolError) + история; fields — root_cause/resolution_summary и т. п."""
    row = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
    if not row:
        raise ToolError(f"инцидент {incident_id} не найден")
    cur = str(row[0])
    transitioned = status != cur
    if transitioned:
        if status not in STATUS_TRANSITIONS.get(cur, set()):
            raise ToolError(f"переход {cur} → {status} недопустим")
        extra = ""
        if status == "in_progress":
            extra = ", taken_sim = coalesce(taken_sim, %s)"
        elif status == "resolved":
            extra = ", resolved_sim = %s, sla_breached = (%s > sla_due_sim)"
        elif status == "closed":
            extra = ", closed_sim = %s"
        args: list[Any] = [status]
        if status == "resolved":
            args += [ctx.sim_time, ctx.sim_time]
        elif extra:
            args.append(ctx.sim_time)
        args.append(incident_id)
        await ctx.conn.execute(
            f"update incidents set status = %s{extra}, updated_at = now() where id = %s", tuple(args)
        )  # noqa: S608 — extra фиксирован кодом
        await _history(ctx, incident_id, cur, status, reason)
    for k, v in (fields or {}).items():
        if k in (
            "root_cause",
            "resolution_summary",
            "team_code",
            "criticality",
            "priority",
            "routing_status",
            "outcome_class",
        ):
            await ctx.conn.execute(f"update incidents set {k} = %s, updated_at = now() where id = %s", (v, incident_id))  # noqa: S608 — k из белого списка
    # Экономика обновляется до WS-события, в том числе без выдачи подарка.
    from app.economics import dcltv

    await dcltv.compute_incident(ctx.conn, incident_id, sim_time=ctx.sim_time)
    brief = await _incident_brief(ctx, incident_id)
    await ctx.notify("incidents", "status", {**brief, "from_status": cur, "reason": reason})
    if transitioned and status in ("resolved", "closed"):
        await agent_gifts.issue_automatic(ctx, incident_id)
    return brief


async def _template_row(
    ctx: ToolContext, code: str, channel: str, segment: str | None, lang: str
) -> tuple[Any, ...] | None:
    row = await ctx.fetchone(
        "select subject, body from notification_templates where code = %s and channel_code = %s and (segment_code = %s or segment_code is null) and lang = %s order by segment_code nulls last limit 1",
        (code, channel, segment, lang),
    )
    if not row:
        row = await ctx.fetchone(
            "select subject, body from notification_templates where code = %s and lang = %s order by (channel_code = 'chat') desc, segment_code nulls last limit 1",
            (code, lang),
        )
    return row


async def render_template(
    ctx: ToolContext,
    code: str,
    channel: str,
    segment: str | None,
    variables: dict[str, Any],
    lang: str = "ru",
) -> tuple[str | None, str]:
    use = lang if lang in ("ru", "en") else "ru"
    row = await _template_row(ctx, code, channel, segment, use)
    if not row and use != "ru":
        row = await _template_row(ctx, code, channel, segment, "ru")
    if not row:
        return None, variables.get("text") or variables.get("summary") or ""
    subject, body = row

    def sub(text: str | None) -> str | None:
        if text is None:
            return None
        out = text
        for k, v in variables.items():
            out = out.replace("{{ " + k + " }}", str(v)).replace("{{" + k + "}}", str(v))
        return re.sub(r"\{\{[^}]*\}\}", "", out).strip()

    return sub(subject), sub(body) or ""


@tool("notify_client")
async def notify_client(
    ctx: ToolContext,
    client_id: int | None,
    signal_id: int,
    incident_id: int | None,
    channel: str,
    template_code: str,
    variables: dict[str, Any],
    text_override: str | None = None,
    segment: str | None = None,
    recipient_type: str = "client",
    consents: dict[str, Any] | None = None,
    lang: str = "ru",
) -> dict[str, Any]:
    """Уведомление клиенту: шаблон по сегменту/каналу (или готовый текст агента), проверка согласий, маскирование ПДн, статус sent, NOTIFY notifications."""
    key = f"{template_code}:{channel}:{recipient_type}"
    dup = await ctx.fetchone(
        "select id, status from notifications where signal_id = %s and template_code = %s and channel_code = %s and recipient_type = %s and run_id = %s",
        (signal_id, template_code, channel, recipient_type, ctx.run_id),
    )
    if dup:
        return {"notification_id": dup[0], "status": dup[1], "deduplicated": True, "key": key}
    subject, body = await render_template(ctx, template_code, channel, segment, variables, lang)
    if text_override:
        body = text_override
    body = PII_RE.sub("****", body)
    status = "sent"
    if consents is not None and channel in ("sms", "email", "push") and consents.get(channel) is False:
        status = "suppressed"
    row = await ctx.fetchone(
        "insert into notifications (run_id, recipient_type, client_id, signal_id, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) returning id",
        (
            ctx.run_id,
            recipient_type,
            client_id,
            signal_id,
            incident_id,
            channel,
            template_code,
            subject,
            body,
            status,
            ctx.sim_time,
        ),
    )
    nid = int(row[0])  # type: ignore[index]
    data = {
        "notification_id": nid,
        "recipient_type": recipient_type,
        "client_id": client_id,
        "incident_id": incident_id,
        "channel": channel,
        "template_code": template_code,
        "status": status,
        "body": body[:400],
    }
    await ctx.notify("notifications", "sent", data)
    if recipient_type == "public":
        await ctx.notify("feed", "reply", data)
    return data


@tool("notify_team")
async def notify_team(
    ctx: ToolContext,
    team_code: str,
    incident_id: int,
    signal_id: int | None,
    text: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dup = await ctx.fetchone(
        "select id from notifications where incident_id = %s and team_code = %s and recipient_type = 'team' and template_code = 'team_notice'",
        (incident_id, team_code),
    )
    if dup:
        return {"notification_id": dup[0], "deduplicated": True}
    subject, body = await render_template(ctx, "team_notice", "internal", None, variables or {})
    body = f"{body}\n\n{text}".strip() if body else text
    row = await ctx.fetchone(
        "insert into notifications (run_id, recipient_type, team_code, signal_id, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, 'team', %s, %s, %s, 'internal', 'team_notice', %s, %s, 'sent', %s, now()) returning id",
        (ctx.run_id, team_code, signal_id, incident_id, subject or f"Инцидент #{incident_id}", body, ctx.sim_time),
    )
    data = {"notification_id": int(row[0]), "team": team_code, "incident_id": incident_id, "body": body[:400]}  # type: ignore[index]
    await ctx.notify("notifications", "team", data)
    await ctx.notify("teams", "notice", data)
    return data


@tool("create_task")
async def create_task(
    ctx: ToolContext,
    kind: str,
    incident_id: int | None,
    client_id: int | None,
    payload: dict[str, Any],
    assignee: str | None = None,
    requires_hitl: bool = False,
    due_sim: dt.datetime | None = None,
) -> dict[str, Any]:
    # Подарок один на инцидент/клиента: стадия gift может повториться после выдачи в resolved.
    # Блокировка инцидента сериализует одновременное создание таких задач.
    if kind == "gift" and incident_id is not None:
        await ctx.conn.execute("select id from incidents where id = %s for update", (incident_id,))
    dup = await ctx.fetchone(
        "select id from tasks where incident_id is not distinct from %s and kind = %s and client_id is not distinct from %s and (status = 'open' or (kind = 'gift' and incident_id is not null)) and run_id = %s order by id limit 1",
        (incident_id, kind, client_id, ctx.run_id),
    )
    if dup:
        return {"task_id": dup[0], "deduplicated": True}
    row = await ctx.fetchone(
        "insert into tasks (run_id, kind, incident_id, client_id, assignee, payload, status, requires_hitl, due_sim, created_sim) values (%s, %s, %s, %s, %s, %s::jsonb, 'open', %s, %s, %s) returning id",
        (
            ctx.run_id,
            kind,
            incident_id,
            client_id,
            assignee or "team_cx",
            dumps(payload),
            requires_hitl,
            due_sim,
            ctx.sim_time,
        ),
    )
    data = {"task_id": int(row[0]), "kind": kind, "incident_id": incident_id, "requires_hitl": requires_hitl}  # type: ignore[index]
    await ctx.notify("tasks", "created", data)
    return data


@tool("request_human_decision")
async def request_human_decision(
    ctx: ToolContext,
    signal_id: int,
    incident_id: int | None,
    reason: str,
    proposal: dict[str, Any],
    options: list[dict[str, str]],
    recommendation: str,
) -> dict[str, Any]:
    dup = await ctx.fetchone(
        "select id from human_decisions where agent_run_id = %s and decision is null", (ctx.agent_run_id,)
    )
    if dup:
        return {"human_decision_id": dup[0], "deduplicated": True}
    row = await ctx.fetchone(
        "insert into human_decisions (sim_run_id, agent_run_id, signal_id, incident_id, requested_sim, reason, agent_proposal, options, recommendation) values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) returning id",
        (
            ctx.run_id,
            ctx.agent_run_id,
            signal_id,
            incident_id,
            ctx.sim_time,
            reason,
            dumps(proposal),
            dumps(options),
            recommendation,
        ),
    )
    hid = int(row[0])  # type: ignore[index]
    if incident_id:
        await update_incident(ctx, incident_id, "awaiting_human", f"HITL: {reason}")
    await ctx.conn.execute("update agent_runs set needed_human = true where id = %s", (ctx.agent_run_id,))
    data = {
        "human_decision_id": hid,
        "signal_id": signal_id,
        "incident_id": incident_id,
        "reason": reason,
        "recommendation": recommendation,
    }
    await ctx.notify("hitl", "requested", data)
    return data


@tool("schedule_followup")
async def schedule_followup(
    ctx: ToolContext,
    signal_id: int,
    incident_id: int | None,
    wake_in_sim_hours: float,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    wake = ctx.sim_time + dt.timedelta(hours=wake_in_sim_hours)
    dup = await ctx.fetchone(
        "select id from followups where agent_run_id = %s and status = 'scheduled'", (ctx.agent_run_id,)
    )
    if dup:
        return {"followup_id": dup[0], "deduplicated": True}
    row = await ctx.fetchone(
        "insert into followups (sim_run_id, agent_run_id, signal_id, incident_id, wake_sim, reason, payload, status) values (%s, %s, %s, %s, %s, %s, %s::jsonb, 'scheduled') returning id",
        (ctx.run_id, ctx.agent_run_id, signal_id, incident_id, wake, reason, dumps(payload or {})),
    )
    return {"followup_id": int(row[0]), "wake_sim": wake, "reason": reason}  # type: ignore[index]


@tool("escalate_to_manager")
async def escalate_to_manager(
    ctx: ToolContext, signal_id: int, incident_id: int | None, reason: str, severity: str, to_role: str = "cx_lead"
) -> dict[str, Any]:
    dup = await ctx.fetchone("select id, public_id from escalations where agent_run_id = %s", (ctx.agent_run_id,))
    if dup:
        await ctx.conn.execute(
            "update escalations set reason = %s, severity = %s where id = %s",
            (
                reason,
                severity if severity in ("low", "medium", "high", "critical") else "high",
                dup[0],
            ),
        )
        return {"escalation_id": dup[0], "public_id": dup[1], "deduplicated": True, "reason_updated": True}
    row = await ctx.fetchone(
        "insert into escalations (run_id, incident_id, signal_id, reason, severity, to_role, status, created_by, agent_run_id, created_sim) values (%s, %s, %s, %s, %s, %s, 'open', 'agent', %s, %s) returning id, public_id",
        (
            ctx.run_id,
            incident_id,
            signal_id,
            reason,
            severity if severity in ("low", "medium", "high", "critical") else "high",
            to_role,
            ctx.agent_run_id,
            ctx.sim_time,
        ),
    )
    assert row is not None
    if incident_id:
        cur_row = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
        if cur_row and "escalated" in STATUS_TRANSITIONS.get(str(cur_row[0]), set()):
            await update_incident(ctx, incident_id, "escalated", reason, {"routing_status": "escalated"})
        else:  # связанный инцидент уже resolved/closed — эскалация фиксируется, статус не откатываем
            await ctx.conn.execute(
                "update incidents set routing_status = 'escalated', updated_at = now() where id = %s", (incident_id,)
            )
    data = {
        "escalation_id": int(row[0]),
        "public_id": row[1],
        "incident_id": incident_id,
        "reason": reason,
        "severity": severity,
        "to_role": to_role,
    }
    await ctx.notify("escalations", "created", data)
    return data


@tool("close_incident")
async def close_incident(
    ctx: ToolContext, incident_id: int, resolution_summary: str, outcome_class: str = "closed_in_sla"
) -> dict[str, Any]:
    brief = await _incident_brief(ctx, incident_id)
    if brief["status"] not in ("resolved", "closed"):
        await update_incident(ctx, incident_id, "resolved", "закрытие агентом")
    if brief["status"] != "closed":
        await update_incident(
            ctx,
            incident_id,
            "closed",
            resolution_summary,
            {"resolution_summary": resolution_summary, "outcome_class": outcome_class},
        )
    return await _incident_brief(ctx, incident_id)


async def set_client_state(
    ctx: ToolContext,
    client_id: int,
    state: str,
    trigger: str,
    signal_id: int | None = None,
    incident_id: int | None = None,
) -> dict[str, Any]:
    await ctx.conn.execute(
        "update client_states set is_current = false where client_id = %s and is_current", (client_id,)
    )
    await ctx.conn.execute(
        "insert into client_states (run_id, client_id, state, since_sim, trigger, incident_id, signal_id, is_current) values (%s, %s, %s, %s, %s, %s, %s, true)",
        (ctx.run_id, client_id, state, ctx.sim_time, trigger, incident_id, signal_id),
    )
    await ctx.notify("clients", "state", {"client_id": client_id, "state": state, "trigger": trigger})
    return {"client_id": client_id, "state": state}


__all__ = [
    "close_incident",
    "create_incident",
    "create_task",
    "escalate_to_manager",
    "link_signal_to_incident",
    "mask_name",
    "notify_client",
    "notify_team",
    "request_human_decision",
    "schedule_followup",
    "set_client_state",
    "update_incident",
]
