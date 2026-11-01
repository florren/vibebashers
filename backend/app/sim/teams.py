"""Эмулятор команд (T-036): план действий по speed_profile, артефакты, регрессии после релиза."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.agent.tools.base import ToolContext
from app.agent.tools.write import STATUS_TRANSITIONS, render_template, update_incident
from app.logging import get_logger
from app.sim.clock import MSK, WORK_END, WORK_START, add_working_days, add_working_hours, is_working_day
from app.sim.events import EventBus, dumps
from app.sim.rng import SimRng

log = get_logger(__name__)

ACTIVE_STATUSES = (
    "routed",
    "in_progress",
    "awaiting_client",
    "fix_proposed",
    "fix_deployed",
    "verifying",
    "escalated",
)
ARTIFACT_FOR_ACTION = {
    "rca": "rca",
    "fix_decision": "fix_decision",
    "progress_report": "progress_report",
    "release": "release_note",
    "verify": "verification_report",
}
ARTIFACT_BODY = {
    "rca": "Первопричина по инциденту {{ title }} в системе {{ system }}: {{ summary }}.",
    "fix_decision": "Решение о внедрении фикса по {{ title }}: устранение в {{ system }}, риски учтены.",
    "progress_report": "День {{ report_day }}: по {{ title }} выполнено {{ done }}, осталось {{ left }}, прогноз {{ eta }}.",
    "release_note": "Релиз исправления по {{ title }} ({{ system }}), версия {{ version }}.",
    "verification_report": "Проверка услуги после фикса {{ title }}: клиентский сценарий проходит штатно.",
}
CLARIFY_QUESTION = "Уточните, пожалуйста, время операции и последние четыре цифры карты (маскированно)."
PII_RE = re.compile(r"\b\d{16}\b|\+7[\d\s\-]{10,}|@[\w.-]+\.(ru|com)\b", re.I)


@dataclass
class PlannedStep:
    action: str
    at: dt.datetime
    report_day: int | None = None
    skipped: bool = False
    regression: dict[str, Any] | None = None
    due: dt.datetime | None = None


@dataclass
class IncidentPlan:
    incident_id: int
    team_code: str
    sla_breach: bool
    do_clarify: bool
    steps: list[PlannedStep] = field(default_factory=list)
    paused_after_clarify: bool = False
    resumed: bool = False
    outcome: str | None = None


@dataclass
class PendingRegression:
    incident_id: int
    release_action_id: int
    release_sim: dt.datetime
    delay_min: int
    error_code: str
    system: str
    product: str | None
    origin_system: str


def _parse_ts(v: Any) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v
    return dt.datetime.fromisoformat(str(v))


def _working_days_between(start: dt.datetime, end: dt.datetime) -> int:
    if end <= start:
        return 0
    cur = start.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    end_d = end.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    days = 0
    while cur < end_d:
        cur += dt.timedelta(days=1)
        if is_working_day(cur):
            days += 1
    return days


def _working_hours_span(start: dt.datetime, end: dt.datetime) -> float:
    """Число полных рабочих сим-часов между моментами (для планирования цепочки)."""
    if end <= start:
        return 1.0
    cur = start
    total = 0.0
    for _ in range(24 * 400):
        if cur >= end:
            break
        nxt = add_working_hours(cur, 1.0)
        if nxt <= cur:
            cur += dt.timedelta(minutes=15)
            continue
        if nxt > end:
            total += (end - cur).total_seconds() / 3600
            break
        total += 1.0
        cur = nxt
    return max(total, 1.0)


def _render_inline(template: str, variables: dict[str, Any]) -> str:
    out = template
    for k, v in variables.items():
        out = out.replace("{{ " + k + " }}", str(v)).replace("{{" + k + "}}", str(v))
    return re.sub(r"\{\{[^}]*\}\}", "", out).strip()


class TeamEmulator:
    """Планирует и исполняет действия команд по инцидентам текущего запуска."""

    def __init__(
        self,
        rng: SimRng,
        conn: psycopg.AsyncConnection[Any],
        bus: EventBus,
        run_id: int,
        *,
        demo_outcome: str | None = None,
        llm: Any = None,
        demo_context: dict[str, Any] | None = None,
        demo_scenario_id: str | None = None,
        incident_ids: list[int] | None = None,
    ) -> None:
        self.incident_ids = incident_ids
        self.demo_context = demo_context or {}
        self.demo_scenario_id = demo_scenario_id
        self.demo_outcome = demo_outcome
        self.llm = llm
        self.artifact_meta: dict[str, Any] = {}
        self.rng = rng
        self.conn = conn
        self.bus = bus
        self.run_id = run_id
        self.plans: dict[int, IncidentPlan] = {}
        self.done: set[tuple[int, str, int | None]] = set()
        self.pending_regressions: list[PendingRegression] = []
        self.error_codes: dict[str, dict[str, Any]] = {}
        self._team_profiles: dict[str, dict[str, Any]] = {}
        self._regressed_incidents: set[int] = set()

    async def load(self) -> None:
        cur = await self.conn.execute("select code, system_code, product_code from error_codes")
        self.error_codes = {r[0]: {"system": r[1], "product": r[2]} for r in await cur.fetchall()}
        cur = await self.conn.execute("select code, speed_profile from teams")
        self._team_profiles = {r[0]: dict(r[1]) for r in await cur.fetchall()}
        release_by_incident: dict[int, tuple[int, dt.datetime]] = {}
        cur = await self.conn.execute(
            "select id, incident_id, action, payload, action_sim from team_actions where run_id = %s order by action_sim, id",
            (self.run_id,),
        )
        for action_id, iid, action, payload, action_sim in await cur.fetchall():
            incident_id = int(iid)
            key = (incident_id, str(action), (payload or {}).get("report_day"))
            self.done.add(key)
            plan_blob = (payload or {}).get("plan")
            if plan_blob:
                self.plans[incident_id] = _plan_from_blob(incident_id, plan_blob)
            if str(action) == "release":
                release_by_incident[incident_id] = (int(action_id), _parse_ts(action_sim))
        cur = await self.conn.execute(
            "select id, caused_by_incident_id from faults where run_id = %s and caused_by_incident_id is not null",
            (self.run_id,),
        )
        self._regressed_incidents = {int(r[1]) for r in await cur.fetchall()}
        if self.incident_ids is not None:
            release_by_incident = {iid: value for iid, value in release_by_incident.items() if iid in self.incident_ids}
        self._restore_pending_regressions(release_by_incident)

    async def tick(self, sim_time: dt.datetime, world: Any) -> None:
        await self._process_regressions(sim_time, world)
        cur = await self.conn.execute(
            "select id, status, team_code, created_sim, take_due_sim, sla_due_sim, report_due_sims, "
            "complexity, criticality, title, system_code, product_code, error_code, agent_run_id "
            "from incidents where run_id = %s and status = any(%s) "
            "and (%s::bigint[] is null or id=any(%s::bigint[]))",
            (self.run_id, list(ACTIVE_STATUSES), self.incident_ids, self.incident_ids),
        )
        for row in await cur.fetchall():
            await self._tick_incident(sim_time, world, row)

    async def _tick_incident(self, sim_time: dt.datetime, world: Any, row: tuple[Any, ...]) -> None:
        (
            iid,
            status,
            team_code,
            created_sim,
            take_due_sim,
            sla_due_sim,
            report_due_sims,
            _complexity,
            _crit,
            title,
            system_code,
            product_code,
            _error_code,
            agent_run_id,
        ) = row
        incident_id = int(iid)
        profile = self._team_profiles.get(str(team_code)) or {}
        plan = self.plans.get(incident_id)
        if plan is not None and plan.outcome and not self.demo_outcome:
            return
        if plan is None:
            plan = self._build_plan(
                incident_id,
                str(team_code),
                profile,
                _parse_ts(created_sim),
                _parse_ts(take_due_sim),
                _parse_ts(sla_due_sim),
                [_parse_ts(x) for x in (report_due_sims or [])],
                str(system_code),
                product_code,
            )
            self.plans[incident_id] = plan

        if plan.do_clarify and plan.paused_after_clarify and status == "in_progress" and not plan.resumed:
            plan.resumed = True

        evidence = self.demo_context
        if self.demo_scenario_id:
            original = await (
                await self.conn.execute(
                    "select 1 from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=%s and s.run_id=%s and s.origin='scenario' and s.meta->>'scenario_id'=%s limit 1",
                    (incident_id, self.run_id, self.demo_scenario_id),
                )
            ).fetchone()
            if not original:
                evidence = {}
        incident_ctx = {
            "demo_evidence": evidence,
            "outcome": plan.outcome,
            "title": title,
            "system": system_code,
            "product": product_code,
            "team": team_code,
        }

        for step in sorted(plan.steps, key=lambda s: s.at):
            if sim_time < step.at:
                continue
            key = (incident_id, step.action, step.report_day)
            if key in self.done or step.skipped:
                continue
            if plan.do_clarify and plan.paused_after_clarify and not plan.resumed:
                if step.action not in ("take", "clarify"):
                    continue
            if step.action in ("rca", "fix_decision", "release", "verify", "close") and status == "awaiting_client":
                continue
            if step.action == "take" and status != "routed" and not (plan.outcome and status == "escalated"):
                self.done.add(key)
                continue
            step_ctx = ToolContext(
                self.conn,
                run_id=self.run_id,
                agent_run_id=int(agent_run_id or 0),
                sim_time=step.at,
                llm_source="mock",
            )
            await self._execute_step(step_ctx, world, plan, step, incident_id, str(team_code), incident_ctx, status)
            status_row = await step_ctx.fetchone("select status from incidents where id = %s", (incident_id,))
            status = str(status_row[0]) if status_row else status

    def _build_plan(
        self,
        incident_id: int,
        team_code: str,
        profile: dict[str, Any],
        created_sim: dt.datetime,
        take_due_sim: dt.datetime,
        sla_due_sim: dt.datetime,
        report_due_sims: list[dt.datetime],
        system_code: str,
        product_code: str | None,
    ) -> IncidentPlan:
        if self.demo_outcome:
            return demo_plan(
                incident_id, team_code, self.demo_outcome, created_sim, take_due_sim, sla_due_sim, report_due_sims
            )
        th = profile.get("take_hours") or [1, 4]
        lo, hi = float(th[0]), float(th[1])
        take_delay = lo if hi <= lo else lo + self.rng.random() * (hi - lo)
        sla_breach = self.rng.random() < float(profile.get("p_sla_breach") or 0)
        do_clarify = self.rng.random() < float(profile.get("p_clarify") or 0)
        factor = float(profile.get("fix_days_factor") or 1.0)

        if sla_breach:
            take_at = add_working_hours(take_due_sim, take_delay)
            close_at = add_working_days(sla_due_sim, 1)
        else:
            take_at = add_working_hours(created_sim, take_delay)
            if take_at > take_due_sim:
                take_at = take_due_sim
            span_h = _working_hours_span(take_at, sla_due_sim)
            close_at = add_working_hours(take_at, span_h * factor)
            if close_at > sla_due_sim:
                close_at = sla_due_sim

        reports: list[PlannedStep] = []
        last_report: dt.datetime | None = None
        for i, due in enumerate(report_due_sims):
            day_no = [3, 6, 9][i] if i < 3 else _working_days_between(created_sim, due)
            skipped = self.rng.random() < 0.10
            if not skipped:
                last_report = due
            reports.append(
                PlannedStep("progress_report", due, report_day=day_no, skipped=skipped),
            )
        steps: list[PlannedStep] = [PlannedStep("take", take_at)]
        chain_start = take_at
        if do_clarify:
            steps.append(PlannedStep("clarify", add_working_hours(take_at, 0.25)))
            chain_start = add_working_hours(take_at, 4)

        span_to_close = _working_hours_span(chain_start, close_at)
        rca_at = add_working_hours(chain_start, 0.5)
        fix_at = add_working_hours(chain_start, max(1.0, span_to_close * 0.35))
        release_at = add_working_hours(chain_start, max(2.0, span_to_close * 0.55))
        verify_at = add_working_hours(chain_start, max(3.0, span_to_close * 0.75))
        if not sla_breach:
            verify_at = min(verify_at, add_working_hours(sla_due_sim, -1.0))
        close_at = max(close_at, add_working_hours(verify_at, 0.5))
        if last_report and not sla_breach:
            close_at = max(close_at, last_report)
        if not sla_breach:
            close_at = min(close_at, sla_due_sim)
        if verify_at >= close_at:
            verify_at = add_working_hours(close_at, -0.5)
        steps.extend(
            [
                PlannedStep("rca", rca_at),
                PlannedStep("fix_decision", fix_at),
                PlannedStep(
                    "release",
                    release_at,
                    regression=self._maybe_regression(profile, system_code, product_code),
                ),
                PlannedStep("verify", verify_at),
                PlannedStep("close", close_at),
            ]
        )
        steps.extend(reports)
        plan = IncidentPlan(incident_id, team_code, sla_breach, do_clarify, steps)
        return plan

    def _maybe_regression(
        self, profile: dict[str, Any], origin_system: str, product_code: str | None
    ) -> dict[str, Any] | None:
        if self.rng.random() >= float(profile.get("p_regression") or 0):
            return None
        candidates = [
            code
            for code, meta in self.error_codes.items()
            if meta.get("system") != origin_system
            and meta.get("product") is not None
            and (product_code is None or meta.get("product") == product_code)
        ]
        if not candidates:
            return None
        code = self.rng.choice(candidates)
        meta = self.error_codes[code]
        return {
            "error_code": code,
            "system": meta["system"],
            "product": meta.get("product"),
            "delay_min": self.rng.randint(60, 240),
            "origin_system": origin_system,
        }

    async def _update_status(
        self,
        ctx: ToolContext,
        incident_id: int,
        current: str,
        target: str,
        reason: str,
    ) -> None:
        cur = current
        if target == "escalated" and cur in ("fix_proposed", "fix_deployed", "verifying"):
            # На локальном времени ручного обращения общий SLA-тик не выполняется.
            # Неудачную попытку возвращаем в работу перед штатной эскалацией.
            await update_incident(ctx, incident_id, "in_progress", "попытка не устранила проблему: возврат в работу")
            cur = "in_progress"
        if cur == "escalated" and target not in STATUS_TRANSITIONS.get("escalated", set()):
            await update_incident(ctx, incident_id, "in_progress", "возврат в работу после эскалации SLA")
            cur = "in_progress"
        if target == "verifying" and cur == "in_progress" and (incident_id, "release", None) in self.done:
            # SLA-эскалация могла вернуть уже выпущенный фикс в работу между release и verify.
            await update_incident(ctx, incident_id, "fix_deployed", "возобновление проверки выпущенного фикса")
            cur = "fix_deployed"
        if target != cur:
            await update_incident(ctx, incident_id, target, reason)

    async def _execute_step(
        self,
        ctx: ToolContext,
        world: Any,
        plan: IncidentPlan,
        step: PlannedStep,
        incident_id: int,
        team_code: str,
        incident_ctx: dict[str, Any],
        status: str,
    ) -> None:
        self.artifact_meta = {}
        key = (incident_id, step.action, step.report_day)
        payload: dict[str, Any] = {"plan": _plan_blob(plan)}
        if plan.outcome:
            payload.update(demo=True, outcome=plan.outcome)
        artifact_id: int | None = None
        artifact_kind: str | None = None

        if step.action == "take":
            await self._update_status(ctx, incident_id, status, "in_progress", "команда взяла в работу")
        elif step.action == "clarify":
            payload["question"] = CLARIFY_QUESTION
            await self._update_status(ctx, incident_id, status, "awaiting_client", "уточнение от команды")
            plan.paused_after_clarify = True
        elif step.action == "escalate_ack":
            if status != "escalated":
                await self._update_status(
                    ctx, incident_id, status, "escalated", "demo: сроки нарушены, устранение не подтверждено"
                )
        elif step.action == "fix_decision":
            await self._update_status(ctx, incident_id, status, "fix_proposed", "решение о фиксе")
        elif step.action == "release":
            await self._update_status(ctx, incident_id, status, "fix_deployed", "релиз фикса")
        elif step.action == "verify":
            await self._update_status(ctx, incident_id, status, "verifying", "проверка услуги")
        elif step.action == "close":
            if plan.outcome:
                check = await ctx.fetchone(
                    "select body_md from incident_artifacts where incident_id=%s and run_id=%s and kind='verification_report' and meta->>'outcome' in ('on_time','late','recovered') order by id desc limit 1",
                    (incident_id, self.run_id),
                )
                if not check:
                    raise ValueError("demo: закрытие без успешного артефакта проверки запрещено")
                await update_incident(
                    ctx,
                    incident_id,
                    status,
                    fields={
                        "resolution_summary": check[0],
                        "outcome_class": "closed_in_sla" if plan.outcome == "on_time" else "closed_late",
                    },
                )
            await self._update_status(ctx, incident_id, status, "resolved", "инцидент устранён")
            status_row = await ctx.fetchone("select status from incidents where id = %s", (incident_id,))
            st = str(status_row[0]) if status_row else status
            await self._update_status(ctx, incident_id, st, "closed", "закрытие командой")

        artifact_kind = ARTIFACT_FOR_ACTION.get(step.action)
        if artifact_kind and not step.skipped:
            body = await self._artifact_body(ctx, artifact_kind, step, incident_ctx)
            title = {
                "rca": "Анализ первопричины",
                "fix_decision": "Решение о внедрении фикса",
                "progress_report": f"Промежуточный отчёт, день {step.report_day}",
                "release_note": "Заметка о релизе",
                "verification_report": "Отчёт о проверке",
            }[artifact_kind]
            cur = await self.conn.execute(
                "insert into incident_artifacts (run_id, incident_id, kind, title, body_md, meta, author_team, generated_by, due_sim, published_sim) "
                "values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s) returning id",
                (
                    self.run_id,
                    incident_id,
                    artifact_kind,
                    title,
                    body,
                    dumps({"report_day": step.report_day, "version": "1.0.0", **self.artifact_meta}),
                    team_code,
                    "llm" if self.artifact_meta.get("source") in ("live", "replay") else "template",
                    (step.due or step.at) if step.action == "progress_report" else None,
                    ctx.sim_time,
                ),
            )
            row = await cur.fetchone()
            artifact_id = int(row[0])  # type: ignore[index]

        if step.action == "release" and step.regression:
            self._queue_regression(incident_id, ctx.sim_time, step, str(incident_ctx.get("system") or ""))

        cur = await self.conn.execute(
            "insert into team_actions (run_id, incident_id, team_code, action, payload, action_sim) "
            "values (%s, %s, %s, %s, %s::jsonb, %s) returning id",
            (
                self.run_id,
                incident_id,
                team_code,
                step.action,
                dumps({**payload, "report_day": step.report_day}),
                ctx.sim_time,
            ),
        )
        action_row = await cur.fetchone()
        action_id = int(action_row[0])  # type: ignore[index]
        event_payload: dict[str, Any] = {
            "action_id": action_id,
            "incident_id": incident_id,
            "team": team_code,
            "action": step.action,
            "action_sim": ctx.sim_time.isoformat(),
            "artifact_id": artifact_id,
            "artifact_kind": artifact_kind,
            "report_day": step.report_day,
            "on_time": ctx.sim_time <= (step.due or step.at) if step.action == "progress_report" else None,
            "payload": payload,
        }
        await self.bus.emit(self.run_id, f"team.{step.action}", event_payload, ctx.sim_time)
        if plan.outcome:
            from app.agent.nodes import Deps

            ar = await ctx.fetchone(
                "insert into agent_runs(kind,sim_run_id,signal_id,incident_id,prompt_version,graph_version,started_sim) "
                "values ('team_emulator',%s,(select signal_id from agent_runs where id=%s),%s,'demo-role-v3','demo-execution-v1',%s) returning id",
                (self.run_id, ctx.agent_run_id, incident_id, ctx.sim_time),
            )
            assert ar is not None
            ctx.agent_run_id = int(ar[0])
            deps = Deps(ctx=ctx, chain=self.llm[0], profile=self.llm[1])
            await deps.record_step(
                "act",
                "ok",
                {"action": step.action},
                {
                    "demo": True,
                    "action": step.action,
                    "artifact_id": artifact_id,
                    "llm_source": self.artifact_meta.get("source", "mock"),
                    "outcome": plan.outcome,
                },
                reasoning="Действие demo-команды по сохранённому плану.",
                model=self.artifact_meta.get("model"),
                usage=self.artifact_meta.get("usage"),
                latency_ms=int((self.artifact_meta.get("usage") or {}).get("latency_ms") or 0),
            )
            from app.demo.roles import finish_run

            await finish_run(self.conn, ctx.agent_run_id, self.artifact_meta)
        self.done.add(key)

        if step.action == "release" and step.regression:
            for pr in reversed(self.pending_regressions):
                if pr.incident_id == incident_id and pr.release_action_id == 0:
                    pr.release_action_id = action_id
                    break

    async def _artifact_body(self, ctx: ToolContext, kind: str, step: PlannedStep, incident_ctx: dict[str, Any]) -> str:
        self.artifact_meta = {}
        outcome = incident_ctx.get("outcome", self.demo_outcome)
        if outcome and self.llm:
            from app.demo.roles import respond

            evidence = incident_ctx.get("demo_evidence", self.demo_context)
            success = outcome in ("on_time", "late", "recovered")
            facts = {
                "role": "product_team",
                "stage": kind,
                "outcome": outcome,
                "language": "ru",
                "subject": incident_ctx["title"],
                "evidence": {"source": evidence.get("source", "demo_emulation")},
                "verified": kind == "verification_report" and success,
            }
            stage_facts = {
                "rca": "Команда завершила диагностику и подготовила разбор причины.",
                "fix_decision": "Подготовлено решение об исправлении; результат ещё не подтверждён.",
                "progress_report": "Команда выполняет работу; проверка устранения ещё не завершена."
                if success
                else "Попытка исправления не устранила проблему. Требуется эскалация.",
                "release_note": "Команда внедрила исправление и передала результат на проверку.",
                "verification_report": f"На стенде проверен согласованный маршрут решения обращения «{incident_ctx['title']}». Внешние действия и движение денег не выполнялись.",
            }
            if evidence:
                stage_facts["rca"] = str(evidence["observed"])
                stage_facts["fix_decision"] = str(evidence["action"])
                stage_facts["verification_report"] = str(evidence["verification"])
            if kind == "fix_decision":
                stage_facts[kind] = "План работы (ещё не выполнен): " + stage_facts[kind]
            facts["result"] = stage_facts[kind]
            fallback = f"{incident_ctx['title']}: {facts['result']}"
            if kind == "verification_report":
                # Результат проверки задаёт стенд, а не свободное заключение модели.
                self.artifact_meta = {
                    "demo": True,
                    "source": "mock",
                    "content_source": "verified_facts",
                    "model": "deterministic-verification",
                    "provider": "mock",
                    "usage": {},
                    "grounded": True,
                    "fallback": False,
                    "outcome": outcome,
                    "stage": kind,
                    "confirmed_result": facts["result"],
                }
                return str(facts["result"])
            obj, self.artifact_meta = await respond(self.llm[0], self.llm[1], facts, fallback)
            self.artifact_meta["outcome"] = outcome
            self.artifact_meta["stage"] = kind
            return PII_RE.sub("****", str(obj["body"]))
        variables = {
            **incident_ctx,
            "summary": incident_ctx.get("title"),
            "report_day": step.report_day or "",
            "done": "диагностика и подготовка патча",
            "left": "релиз и проверка",
            "eta": "в срок SLA",
            "version": "1.0.0",
            "text": _render_inline(ARTIFACT_BODY.get(kind.replace("release", "release_note"), ""), incident_ctx),
        }
        _, body = await render_template(ctx, kind, "internal", None, variables)
        if not body:
            body = variables["text"]
        return body

    def _restore_pending_regressions(self, release_by_incident: dict[int, tuple[int, dt.datetime]]) -> None:
        for incident_id, plan in self.plans.items():
            if incident_id in self._regressed_incidents:
                continue
            release_step = next((s for s in plan.steps if s.action == "release"), None)
            if release_step is None or not release_step.regression:
                continue
            key = (incident_id, "release", release_step.report_day)
            if key not in self.done:
                continue
            release_action_id, release_sim = release_by_incident.get(incident_id, (0, release_step.at))
            reg = release_step.regression
            if not reg.get("error_code"):
                continue
            self.pending_regressions.append(
                PendingRegression(
                    incident_id,
                    release_action_id,
                    release_sim,
                    int(reg["delay_min"]),
                    str(reg["error_code"]),
                    str(reg["system"]),
                    reg.get("product"),
                    str(reg.get("origin_system") or ""),
                )
            )

    def _queue_regression(
        self, incident_id: int, release_sim: dt.datetime, step: PlannedStep, origin_system: str
    ) -> None:
        reg = step.regression or {}
        if not reg.get("error_code"):
            return
        self.pending_regressions.append(
            PendingRegression(
                incident_id,
                0,
                release_sim,
                int(reg["delay_min"]),
                str(reg["error_code"]),
                str(reg["system"]),
                reg.get("product"),
                reg.get("origin_system") or origin_system,
            )
        )

    async def _process_regressions(self, sim_time: dt.datetime, world: Any) -> None:
        for pr in list(self.pending_regressions):
            if self.incident_ids is not None and pr.incident_id not in self.incident_ids:
                continue
            if sim_time < pr.release_sim + dt.timedelta(minutes=pr.delay_min):
                continue
            if pr.incident_id in getattr(self, "_regressed_incidents", set()):
                self.pending_regressions.remove(pr)
                continue
            cur = await self.conn.execute(
                "select 1 from faults where run_id = %s and caused_by_incident_id = %s limit 1",
                (self.run_id, pr.incident_id),
            )
            if await cur.fetchone():
                self._regressed_incidents.add(pr.incident_id)
                self.pending_regressions.remove(pr)
                continue
            cur = await self.conn.execute(
                "insert into faults (run_id, system_code, error_code, started_sim, caused_by_incident_id, region_codes) "
                "values (%s, %s, %s, %s, %s, %s) returning id",
                (self.run_id, pr.system, pr.error_code, sim_time, pr.incident_id, []),
            )
            fid = int((await cur.fetchone())[0])  # type: ignore[index]
            payload = {
                "fault_id": fid,
                "caused_by_incident_id": pr.incident_id,
                "release_action_id": pr.release_action_id,
                "origin_system": pr.origin_system,
                "system": pr.system,
                "error_code": pr.error_code,
                "product": pr.product,
                "delay_min": pr.delay_min,
                "impact_count": 0,
                "started_sim": sim_time.isoformat(),
            }
            await self.bus.emit(self.run_id, "fault.regression", payload, sim_time)
            world.active_faults.append(
                {
                    "id": fid,
                    "system": pr.system,
                    "error_code": pr.error_code,
                    "started_sim": sim_time,
                    "expected_end": sim_time + dt.timedelta(minutes=90),
                    "impact": 0,
                    "clients": set(),
                    "corr": __import__("uuid").uuid4(),
                }
            )
            self._regressed_incidents.add(pr.incident_id)
            self.pending_regressions.remove(pr)


def _plan_blob(plan: IncidentPlan) -> dict[str, Any]:
    return {
        "team_code": plan.team_code,
        "sla_breach": plan.sla_breach,
        "do_clarify": plan.do_clarify,
        "outcome": plan.outcome,
        "steps": [
            {
                "action": s.action,
                "at": s.at.isoformat(),
                "report_day": s.report_day,
                "skipped": s.skipped,
                "regression": s.regression,
                "due": s.due.isoformat() if s.due else None,
            }
            for s in plan.steps
        ],
    }


def _plan_from_blob(incident_id: int, blob: dict[str, Any]) -> IncidentPlan:
    steps = [
        PlannedStep(
            s["action"],
            _parse_ts(s["at"]),
            report_day=s.get("report_day"),
            skipped=bool(s.get("skipped")),
            regression=s.get("regression"),
            due=_parse_ts(s["due"]) if s.get("due") else None,
        )
        for s in blob.get("steps") or []
    ]
    return IncidentPlan(
        incident_id,
        str(blob.get("team_code") or ""),
        bool(blob.get("sla_breach")),
        bool(blob.get("do_clarify")),
        steps,
        outcome=blob.get("outcome"),
    )


__all__ = ["TeamEmulator", "PII_RE", "ACTIVE_STATUSES"]


def _before_working_hours(at: dt.datetime, hours: float) -> dt.datetime:
    """Обратный рабочий интервал; add_working_hours поддерживает только движение вперёд."""
    current = at.astimezone(MSK)
    remaining = dt.timedelta(hours=hours)
    if remaining < dt.timedelta(0):
        raise ValueError("обратный рабочий интервал должен быть неотрицательным")
    while remaining > dt.timedelta(0):
        start = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
        end = current.replace(hour=WORK_END, minute=0, second=0, microsecond=0)
        if not is_working_day(current) or current <= start:
            current = (current - dt.timedelta(days=1)).replace(hour=WORK_END, minute=0, second=0, microsecond=0)
            while not is_working_day(current):
                current -= dt.timedelta(days=1)
            continue
        current = min(current, end)
        step = min(remaining, current - start)
        current -= step
        remaining -= step
    return current


def demo_plan(
    incident_id: int,
    team_code: str,
    outcome: str,
    created: dt.datetime,
    take_due: dt.datetime,
    due: dt.datetime,
    report_dues: list[dt.datetime] | None = None,
) -> IncidentPlan:
    """Пять детерминированных траекторий; SLA остаётся из контракта, время — рабочее."""
    if outcome not in ("on_time", "late", "no_work", "failed", "recovered"):
        raise ValueError("неизвестный исход demo-команды")
    late = outcome != "on_time"
    start = add_working_hours(take_due, 1) if late else created
    if outcome == "no_work":
        steps = [PlannedStep("escalate_ack", add_working_hours(due, 1))]
    else:
        close_at = (
            add_working_hours(due, 8 if outcome == "recovered" else 4)
            if late
            else max(created, _before_working_hours(due, 0.25))
        )
        from app.sim.sla import working_seconds_between

        span = max(0.0, working_seconds_between(start, close_at) / 3600)
        steps = [PlannedStep("take", start)]
        for action, fraction in (("rca", 0.1), ("fix_decision", 0.2), ("progress_report", 0.35)):
            steps.append(PlannedStep(action, add_working_hours(start, span * fraction)))
        if outcome in ("failed", "recovered"):
            steps.append(PlannedStep("escalate_ack", add_working_hours(due, 0.5)))
        if outcome != "failed":
            release_at = min(close_at, add_working_hours(start, span * 0.8))
            if outcome == "recovered":
                release_at = max(release_at, add_working_hours(due, 1))
            verify_at = max(release_at, min(close_at, add_working_hours(start, span * 0.9)))
            steps.extend(
                [PlannedStep("release", release_at), PlannedStep("verify", verify_at), PlannedStep("close", close_at)]
            )
    if outcome == "on_time" and report_dues:
        # Проверка SLA сопоставляет отчёт с исходным due_sim; ранняя публикация не меняет дедлайн.
        steps = [s for s in steps if s.action != "progress_report"]
        close_time = next(s.at for s in steps if s.action == "close")
        for report_due in report_dues:
            if report_due < close_time:
                steps.append(
                    PlannedStep(
                        "progress_report",
                        max(created, _before_working_hours(report_due, 0.25)),
                        report_day=_working_days_between(created, report_due),
                        due=report_due,
                    )
                )
    return IncidentPlan(incident_id, team_code, late, False, sorted(steps, key=lambda s: s.at), outcome=outcome)
