"""SLA-движок симулятора (T-037): тики 15 сим-мин, предупреждения, срывы, отчёты, эскалации."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg

from app.agent.tools.base import ToolContext
from app.agent.tools.write import STATUS_TRANSITIONS, render_template, update_incident
from app.economics import dcltv
from app.logging import get_logger
from app.sim.clock import MSK, WORK_END, WORK_START, add_working_days, is_working_day, is_working_time
from app.sim.events import EventBus, dumps

log = get_logger(__name__)

SLA_MONITOR_STATUSES = (
    "routed",
    "in_progress",
    "awaiting_client",
    "fix_proposed",
    "fix_deployed",
    "verifying",
    "escalated",
    "awaiting_human",
    "resolved",
)
TERMINAL_STATUSES = frozenset({"closed", "duplicate", "rejected", "new"})
SLA_TICK_EXCLUDED = frozenset({"duplicate", "rejected", "new"})


def fix_deadline(created: dt.datetime, fix_days: int) -> dt.datetime:
    """Срок устранения = fix_days рабочих дней от created (время суток сохраняется)."""
    return add_working_days(created, fix_days)


def _parse_ts(v: Any) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v
    return dt.datetime.fromisoformat(str(v))


def _align_15(t: dt.datetime) -> dt.datetime:
    lt = t.astimezone(MSK).replace(second=0, microsecond=0)
    return lt.replace(minute=(lt.minute // 15) * 15)


def is_sla_tick_mark(t: dt.datetime) -> bool:
    lt = t.astimezone(MSK)
    return lt.second == 0 and lt.microsecond == 0 and lt.minute % 15 == 0


def sla_tick_times(t0: dt.datetime, t1: dt.datetime) -> list[dt.datetime]:
    """Моменты sla.tick: каждые 15 сим-мин в (t0, t1]; хвост на t1, если он не на метке и был тик на метке."""
    if t1 <= t0:
        return []
    times: list[dt.datetime] = []
    cur = _align_15(t0)
    if cur <= t0:
        cur += dt.timedelta(minutes=15)
    while cur <= t1:
        times.append(cur)
        cur += dt.timedelta(minutes=15)
    if times and not is_sla_tick_mark(t1) and t1 > times[-1]:
        times.append(t1)
    return times


def working_seconds_between(start: dt.datetime, end: dt.datetime) -> float:
    """Рабочие секунды 09:00–18:00 пн–пт между start и end (не включая end)."""
    if end <= start:
        return 0.0
    cur = start.astimezone(MSK)
    end = end.astimezone(MSK)
    total = 0.0
    for _ in range(24 * 400):
        if cur >= end:
            break
        if not is_working_time(cur):
            nxt = cur.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
            if cur.hour >= WORK_END or not is_working_day(cur) or cur >= nxt:
                nxt += dt.timedelta(days=1)
            while not is_working_day(nxt):
                nxt += dt.timedelta(days=1)
            cur = nxt
            continue
        day_end = cur.replace(hour=WORK_END, minute=0, second=0, microsecond=0)
        seg_end = min(end, day_end)
        if seg_end > cur:
            total += (seg_end - cur).total_seconds()
        cur = seg_end
        if cur >= day_end:
            nxt_day = (cur + dt.timedelta(days=1)).replace(hour=WORK_START, minute=0, second=0, microsecond=0)
            while not is_working_day(nxt_day):
                nxt_day += dt.timedelta(days=1)
            cur = nxt_day
    return total


def remaining_pct(
    created_sim: dt.datetime,
    sla_due_sim: dt.datetime,
    at: dt.datetime,
    *,
    complexity: str,
) -> float:
    """Доля оставшегося SLA (0–100+); instant — по календарному интервалу."""
    if at >= sla_due_sim:
        return 0.0
    if complexity == "instant":
        total = (sla_due_sim - created_sim).total_seconds()
        if total <= 0:
            return 0.0
        left = (sla_due_sim - at).total_seconds()
        return max(0.0, 100.0 * left / total)
    total = working_seconds_between(created_sim, sla_due_sim)
    if total <= 0:
        return 0.0
    left = working_seconds_between(at, sla_due_sim)
    return max(0.0, 100.0 * left / total)


class SlaEngine:
    """Пересчёт SLA и эскалации по инцидентам текущего запуска."""

    def __init__(
        self,
        conn: psycopg.AsyncConnection[Any],
        bus: EventBus,
        run_id: int,
    ) -> None:
        self.conn = conn
        self.bus = bus
        self.run_id = run_id
        self._cursor: dt.datetime | None = None
        self._segments: dict[str, int] = {}

    async def load(self) -> None:
        cur = await self.conn.execute(
            "select max(sim_time) from sim_events where run_id = %s and event_type = 'sla.tick'",
            (self.run_id,),
        )
        row = await cur.fetchone()
        self._cursor = _parse_ts(row[0]) if row and row[0] else None
        cur = await self.conn.execute("select code, first_response_min from segments")
        self._segments = {str(r[0]): int(r[1]) for r in await cur.fetchall()}

    async def tick(self, t0: dt.datetime, t1: dt.datetime) -> None:
        for at in sla_tick_times(t0, t1):
            if self._cursor is not None and at <= self._cursor:
                continue
            await self._tick_at(at)
            self._cursor = at

    async def _tick_at(self, sim_time: dt.datetime) -> None:
        ctx = ToolContext(self.conn, run_id=self.run_id, agent_run_id=0, sim_time=sim_time, llm_source="template")
        cur = await self.conn.execute(
            "select id, status, team_code, created_sim, take_due_sim, sla_due_sim, report_due_sims, "
            "complexity, sla_breached, outcome_class, agent_run_id "
            "from incidents where run_id = %s and status <> all(%s)",
            (self.run_id, list(SLA_TICK_EXCLUDED)),
        )
        rows = await cur.fetchall()
        counts = {"open": 0, "warning": 0, "breached": 0, "reports_due": 0}
        for row in rows:
            await self._process_incident(ctx, row, sim_time, counts)
        await self._process_first_response(ctx, sim_time)
        payload = {
            "incident_id": None,
            "signal_id": None,
            "team": None,
            "remaining_pct": None,
            "due_sim": None,
            "report_day": None,
            "escalate_to": None,
            "counts": counts,
            "sim_time": sim_time.isoformat(),
        }
        await self.bus.emit(self.run_id, "sla.tick", payload, sim_time)
        await ctx.notify("sim", "event", {"event_type": "sla.tick", "counts": counts, "sim_time": sim_time.isoformat()})

    async def _process_incident(
        self,
        ctx: ToolContext,
        row: tuple[Any, ...],
        sim_time: dt.datetime,
        counts: dict[str, int],
    ) -> None:
        (
            iid,
            status,
            team_code,
            created_sim,
            take_due_sim,
            sla_due_sim,
            report_due_sims,
            complexity,
            sla_breached,
            outcome_class,
            agent_run_id,
        ) = row
        incident_id = int(iid)
        if str(status) == "closed":
            if not outcome_class or str(outcome_class) == "open":
                await dcltv.compute_incident(self.conn, incident_id, sim_time=sim_time)
            return
        created = _parse_ts(created_sim)
        due = _parse_ts(sla_due_sim)
        take_due = _parse_ts(take_due_sim)
        pct = remaining_pct(created, due, sim_time, complexity=str(complexity or "medium"))
        breached = bool(sla_breached) or sim_time >= due
        if breached:
            counts["breached"] += 1
        elif pct < 25.0:
            counts["warning"] += 1
        elif str(status) in SLA_MONITOR_STATUSES:
            counts["open"] += 1

        if not breached and pct < 25.0:
            await self._emit_once(
                ctx,
                "sla.warning",
                incident_id,
                None,
                {
                    "incident_id": incident_id,
                    "team": team_code,
                    "remaining_pct": round(pct, 2),
                    "due_sim": due.isoformat(),
                    "sim_time": sim_time.isoformat(),
                },
                sim_time,
            )
            await ctx.notify(
                "incidents",
                "sla_warning",
                {"incident_id": incident_id, "remaining_pct": round(pct, 2), "team": team_code},
            )

        if sim_time >= due and not sla_breached:
            breach_reason = "срыв SLA по сроку устранения"
            if await self._escalate_on_sla_breach(ctx, incident_id, agent_run_id, breach_reason):
                await self.conn.execute(
                    "update incidents set sla_breached = true, updated_at = now() where id = %s", (incident_id,)
                )
                await self._emit_once(
                    ctx,
                    "sla.breached",
                    incident_id,
                    due.isoformat(),
                    {
                        "incident_id": incident_id,
                        "team": team_code,
                        "remaining_pct": 0.0,
                        "due_sim": due.isoformat(),
                        "sim_time": sim_time.isoformat(),
                    },
                    sim_time,
                )
                await ctx.notify("incidents", "sla_breached", {"incident_id": incident_id, "team": team_code})
                await self._notify_sla(ctx, incident_id, str(team_code), "sla_breach")
                await self._emit_once(
                    ctx,
                    "sla.escalated",
                    incident_id,
                    due.isoformat(),
                    {
                        "incident_id": incident_id,
                        "team": team_code,
                        "escalate_to": "cx_lead",
                        "due_sim": due.isoformat(),
                        "sim_time": sim_time.isoformat(),
                    },
                    sim_time,
                )
                await dcltv.compute_incident(self.conn, incident_id, sim_time=sim_time)

        reports = [_parse_ts(x) for x in (report_due_sims or [])]
        for due_report in reports:
            if sim_time < due_report:
                continue
            counts["reports_due"] += 1
            report_day = max(1, (due_report.date() - created.date()).days or 1)
            await self._emit_once(
                ctx,
                "sla.report_due",
                incident_id,
                due_report.isoformat(),
                {
                    "incident_id": incident_id,
                    "team": team_code,
                    "due_sim": due_report.isoformat(),
                    "report_day": report_day,
                    "sim_time": sim_time.isoformat(),
                },
                sim_time,
            )
            if await self._has_progress_report(incident_id, due_report, sim_time):
                continue
            await self._emit_once(
                ctx,
                "sla.report_missing",
                incident_id,
                due_report.isoformat(),
                {
                    "incident_id": incident_id,
                    "team": team_code,
                    "due_sim": due_report.isoformat(),
                    "report_day": report_day,
                    "sim_time": sim_time.isoformat(),
                },
                sim_time,
            )
            await self._notify_sla(ctx, incident_id, str(team_code), "sla_report_missing")
            await self._insert_followup(ctx, incident_id, agent_run_id, "report_due", due_report, sim_time)
            misses = await self._report_miss_count(incident_id)
            if misses >= 2:
                await self._insert_escalation(ctx, incident_id, agent_run_id, "повторный пропуск промежуточного отчёта")
                cur_st = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
                if cur_st and "escalated" in STATUS_TRANSITIONS.get(str(cur_st[0]), set()):
                    await update_incident(ctx, incident_id, "escalated", "пропуск промежуточного отчёта SLA")
                await self._emit_once(
                    ctx,
                    "sla.escalated",
                    incident_id,
                    due_report.isoformat(),
                    {
                        "incident_id": incident_id,
                        "team": team_code,
                        "escalate_to": "cx_lead",
                        "due_sim": due_report.isoformat(),
                        "sim_time": sim_time.isoformat(),
                    },
                    sim_time,
                )
                await self._insert_followup(ctx, incident_id, agent_run_id, "escalation_check", due_report, sim_time)

        cur_taken = await ctx.fetchone("select taken_sim from incidents where id = %s", (incident_id,))
        taken_sim = cur_taken[0] if cur_taken else None
        if taken_sim is None and sim_time > take_due:
            await self._emit_once(
                ctx,
                "sla.take_overdue",
                incident_id,
                take_due.isoformat(),
                {
                    "incident_id": incident_id,
                    "team": team_code,
                    "due_sim": take_due.isoformat(),
                    "sim_time": sim_time.isoformat(),
                },
                sim_time,
            )

        if str(status) in ("resolved", "closed") and (not outcome_class or str(outcome_class) == "open"):
            await dcltv.compute_incident(self.conn, incident_id, sim_time=sim_time)

    async def _process_first_response(self, ctx: ToolContext, sim_time: dt.datetime) -> None:
        cur = await self.conn.execute(
            "select s.id, s.received_sim, s.segment_code, isg.incident_id "
            "from signals s "
            "join incident_signals isg on isg.signal_id = s.id and isg.link_type = 'primary' "
            "join incidents i on i.id = isg.incident_id "
            "where s.run_id = %s and i.status <> all(%s) "
            "and not exists (select 1 from notifications n where n.signal_id = s.id and n.recipient_type = 'client' and n.status = 'sent')",
            (self.run_id, list(TERMINAL_STATUSES)),
        )
        for signal_id, received_sim, segment_code, incident_id in await cur.fetchall():
            limit_min = self._segments.get(str(segment_code), 60)
            received = _parse_ts(received_sim)
            if sim_time < received + dt.timedelta(minutes=limit_min):
                continue
            await self._emit_once(
                ctx,
                "sla.first_response_overdue",
                int(signal_id),
                None,
                {
                    "incident_id": int(incident_id),
                    "signal_id": int(signal_id),
                    "due_sim": (received + dt.timedelta(minutes=limit_min)).isoformat(),
                    "sim_time": sim_time.isoformat(),
                },
                sim_time,
                dedupe_key=f"sig:{signal_id}",
            )

    async def _has_progress_report(self, incident_id: int, due_report: dt.datetime, sim_time: dt.datetime) -> bool:
        cur = await self.conn.execute(
            "select 1 from incident_artifacts where incident_id = %s and kind = 'progress_report' "
            "and due_sim = %s and published_sim is not null and published_sim <= %s limit 1",
            (incident_id, due_report, sim_time),
        )
        return (await cur.fetchone()) is not None

    async def _report_miss_count(self, incident_id: int) -> int:
        cur = await self.conn.execute(
            "select count(distinct payload->>'due_sim') from sim_events where run_id = %s and event_type = 'sla.report_missing' "
            "and payload->>'incident_id' = %s",
            (self.run_id, str(incident_id)),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def _emit_once(
        self,
        ctx: ToolContext,
        event_type: str,
        incident_id: int | None,
        due_sim: str | None,
        payload: dict[str, Any],
        sim_time: dt.datetime,
        *,
        dedupe_key: str | None = None,
    ) -> None:
        if dedupe_key and dedupe_key.startswith("sig:"):
            cur = await self.conn.execute(
                "select 1 from sim_events where run_id = %s and event_type = %s and payload->>'signal_id' = %s limit 1",
                (self.run_id, event_type, dedupe_key.replace("sig:", "")),
            )
        elif event_type == "sla.warning":
            cur = await self.conn.execute(
                "select 1 from sim_events where run_id = %s and event_type = %s and payload->>'incident_id' = %s limit 1",
                (self.run_id, event_type, str(incident_id)),
            )
        else:
            cur = await self.conn.execute(
                "select 1 from sim_events where run_id = %s and event_type = %s "
                "and payload->>'incident_id' = %s and coalesce(payload->>'due_sim', '') = coalesce(%s, '') limit 1",
                (self.run_id, event_type, str(incident_id or ""), due_sim or ""),
            )
        if await cur.fetchone():
            return
        await self.bus.emit(self.run_id, event_type, payload, sim_time)

    async def _escalate_on_sla_breach(
        self,
        ctx: ToolContext,
        incident_id: int,
        agent_run_id: Any,
        reason: str,
    ) -> bool:
        """Эскалация при срыве SLA по FSM; True — статус escalated и запись в escalations."""
        cur_st = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
        if not cur_st:
            return False
        current = str(cur_st[0])
        if "escalated" in STATUS_TRANSITIONS.get(current, set()):
            await update_incident(ctx, incident_id, "escalated", reason)
            await self._insert_escalation(ctx, incident_id, agent_run_id, reason)
            return True
        if "in_progress" in STATUS_TRANSITIONS.get(current, set()):
            await update_incident(ctx, incident_id, "in_progress", reason)
            cur_st = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
            after = str(cur_st[0]) if cur_st else "in_progress"
            if "escalated" in STATUS_TRANSITIONS.get(after, set()):
                await update_incident(ctx, incident_id, "escalated", reason)
                await self._insert_escalation(ctx, incident_id, agent_run_id, reason)
                return True
        return False

    async def _notify_sla(self, ctx: ToolContext, incident_id: int, team_code: str, template_code: str) -> None:
        variables = {"incident_id": incident_id, "team": team_code}
        for recipient_type, team in (("team", team_code), ("cx", "team_cx")):
            dup = await ctx.fetchone(
                "select id from notifications where run_id = %s and incident_id = %s and template_code = %s "
                "and recipient_type = %s and (team_code is not distinct from %s)",
                (self.run_id, incident_id, template_code, recipient_type, team if recipient_type == "team" else None),
            )
            if dup:
                continue
            _subj, body = await render_template(ctx, template_code, "internal", None, variables)
            await self.conn.execute(
                "insert into notifications (run_id, recipient_type, team_code, incident_id, channel_code, template_code, "
                "subject, body, status, sent_sim, sent_at) values (%s, %s, %s, %s, 'internal', %s, %s, %s, 'sent', %s, now())",
                (
                    self.run_id,
                    recipient_type,
                    team if recipient_type == "team" else None,
                    incident_id,
                    template_code,
                    _subj or f"SLA: {template_code}",
                    body or f"Инцидент #{incident_id}: {template_code}",
                    ctx.sim_time,
                ),
            )

    async def _insert_escalation(self, ctx: ToolContext, incident_id: int, agent_run_id: Any, reason: str) -> None:
        dup = await ctx.fetchone(
            "select id from escalations where run_id = %s and incident_id = %s and to_role = 'cx_lead' and reason = %s",
            (self.run_id, incident_id, reason),
        )
        if dup:
            return
        await self.conn.execute(
            "insert into escalations (run_id, incident_id, signal_id, reason, severity, to_role, status, created_by, agent_run_id, created_sim) "
            "values (%s, %s, null, %s, 'high', 'cx_lead', 'open', 'agent', %s, %s)",
            (self.run_id, incident_id, reason, int(agent_run_id or 0) or None, ctx.sim_time),
        )

    async def _insert_followup(
        self,
        ctx: ToolContext,
        incident_id: int,
        agent_run_id: Any,
        reason: str,
        due_report: dt.datetime,
        sim_time: dt.datetime,
    ) -> None:
        dup = await ctx.fetchone(
            "select id from followups where sim_run_id = %s and incident_id = %s and reason = %s and payload->>'due_sim' = %s",
            (self.run_id, incident_id, reason, due_report.isoformat()),
        )
        if dup:
            return
        await self.conn.execute(
            "insert into followups (sim_run_id, agent_run_id, signal_id, incident_id, wake_sim, reason, payload, status) "
            "values (%s, %s, null, %s, %s, %s, %s::jsonb, 'fired')",
            (
                self.run_id,
                int(agent_run_id or 0) or None,
                incident_id,
                sim_time,
                reason,
                dumps({"due_sim": due_report.isoformat()}),
            ),
        )


__all__ = [
    "SlaEngine",
    "fix_deadline",
    "is_sla_tick_mark",
    "remaining_pct",
    "sla_tick_times",
    "working_seconds_between",
]
