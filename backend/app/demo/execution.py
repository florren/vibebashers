"""Изолированное demo-исполнение: сотрудники и команды, сохранённые факты, событийное время."""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from typing import Any

import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import tuple_row

from app.agent.nodes import Deps
from app.agent.tools.base import ToolContext
from app.agent.tools.write import link_signal_to_incident, notify_client
from app.api.hitl import HitlDecisionBody, post_hitl_id
from app.compliance.session import ComplianceService
from app.db.session import psycopg_dsn
from app.demo.roles import finish_run, respond
from app.demo.settings import configuration as configuration
from app.demo.settings import ensure
from app.demo.settings import save as save
from app.ingest.normalizer import create_signal
from app.logging import get_logger
from app.sim import scenarios
from app.sim.events import EventBus
from app.sim.rng import SimRng
from app.sim.sla import SlaEngine
from app.sim.teams import TeamEmulator

log = get_logger(__name__)


async def execution_active(app: Any, conn: Any, run_id: int, *, manual_only: bool = False) -> bool:
    config = await configuration(conn, run_id)
    return bool(
        app.state.sim.run_id == run_id
        and config.get("enabled")
        and (
            (manual_only and config.get("mode") == "simulation" and config.get("auto_advance"))
            or (app.state.sim.clock.running and config.get("status") == "running")
        )
    )


async def employees(app: Any, conn: Any, run_id: int, at: dt.datetime, *, manual_only: bool = False) -> bool:
    """Один ответ за цикл; ручное решение выигрывает гонку благодаря штатной блокировке HITL."""
    svc = app.state.agent
    request = Request({"type": "http", "app": app, "headers": []})
    cur = await conn.execute(
        "select h.id,h.reason,h.agent_proposal from human_decisions h left join agent_runs a on a.id=h.agent_run_id "
        "where h.sim_run_id=%s and (%s=false or exists(select 1 from signals ms where ms.id=a.signal_id and (ms.origin='jury' or ms.channel_subtype='ui_pers_demo'))) and h.decision is null and (a.outcome is not null or a.id is null) "
        "and (h.agent_proposal->>'kind'='escalation' or a.id is null or exists(select 1 from agent_steps s where s.run_id=a.id and s.node='wait_human' and s.output->>'human_decision_id'=h.id::text)) order by h.id limit 1",
        (run_id, manual_only),
    )
    row = await cur.fetchone()
    if row:
        hid, reason, proposal = row
        profile = svc.chain.profile_for("twin", svc.profile)
        obj, meta = await respond(
            svc.chain,
            profile,
            {"role": "bank_operator", "reason": reason, "proposal": proposal, "language": "ru"},
            "Демонстрационный оператор рассмотрел предложение агента и согласовал исполнение в пределах действующих правил.",
        )
        decision = obj["decision"] if obj["decision"] in ("accept", "reject") else "reject"
        async with app.state.sim._lock:
            if app.state.sim.run_id != run_id or not await execution_active(app, conn, run_id, manual_only=manual_only):
                return False
            try:
                await post_hitl_id(
                    request,
                    int(hid),
                    HitlDecisionBody(
                        decision=decision,
                        decided_by=f"demo-agent:operator:{meta['source']}",
                        comment="[DEMO] " + obj["body"] + " · " + str(meta["model"]),
                        use_as_fewshot=False,
                    ),
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        return True
    if manual_only:
        return False
    alert = await (
        await conn.execute(
            "select a.id,a.recommendation_ru,(select jsonb_agg(t.quote order by t.id) from compliance_triggers t where t.session_id=s.id and t.status='confirmed') from compliance_alerts a join audio_sessions s on s.id=a.session_id where s.run_id=%s and a.acknowledged_at is null and (s.transcript_id is null or exists(select 1 from transcripts tr where tr.id=s.transcript_id and tr.status='done')) order by a.id limit 1",
            (run_id,),
        )
    ).fetchone()
    if alert:
        obj, meta = await respond(
            svc.chain,
            svc.chain.profile_for("twin", svc.profile),
            {
                "role": "branch_manager",
                "language": "ru",
                "alert_id": alert[0],
                "recommendation": alert[1],
                "confirmed_quotes": alert[2],
            },
            "Демонстрационный руководитель подтвердил разбор нарушения и поручил устранить проблему клиента.",
            "open_incident",
        )
        if app.state.sim.run_id != run_id or not await execution_active(app, conn, run_id, manual_only=manual_only):
            return False
        # Не разрешаем модели отбрасывать подтверждённое нарушение без доказательств.
        async with app.state.sim._lock, conn.transaction():
            if not await execution_active(app, conn, run_id, manual_only=manual_only):
                return False
            locked = await (
                await conn.execute(
                    "select a.id from compliance_alerts a join audio_sessions s on s.id=a.session_id where a.id=%s and s.run_id=%s and a.acknowledged_at is null for update of a",
                    (alert[0], run_id),
                )
            ).fetchone()
            if locked:
                service = ComplianceService(conn, run_id=run_id, sim_time=at, chain=svc.chain, profile=svc.profile)
                await service.ack_alert(
                    int(alert[0]),
                    decision="open_incident",
                    by=f"demo-agent:manager:{meta['source']}",
                    comment="[DEMO] " + obj["body"],
                )
                await compliance_customer_case(conn, app, run_id, int(alert[0]), at, meta)
        return True
    return False


async def compliance_customer_case(
    conn: Any, app: Any, run_id: int, alert_id: int, at: dt.datetime, meta: dict[str, Any]
) -> None:
    """Инструменты используют tuple-строки; HTTP-роутер передаёт dict_row в той же транзакции."""
    original_factory = conn.row_factory
    try:
        conn.row_factory = tuple_row
        await _compliance_customer_case(conn, app, run_id, alert_id, at, meta)
    finally:
        conn.row_factory = original_factory


async def _compliance_customer_case(
    conn: Any, app: Any, run_id: int, alert_id: int, at: dt.datetime, meta: dict[str, Any]
) -> None:
    """Подтверждённое нарушение требует ответа клиенту даже без его жалобы."""
    row = await (
        await conn.execute(
            "select s.id,s.client_id,s.transcript_id,a.incident_id from compliance_alerts a join audio_sessions s on s.id=a.session_id where a.id=%s and s.run_id=%s",
            (alert_id, run_id),
        )
    ).fetchone()
    if not row or not row[1] or not row[3]:
        return
    session_id, client_id, transcript_id, incident_id = row
    existing = (
        await (
            await conn.execute(
                "select id from signals where run_id=%s and transcript_id=%s and client_id=%s order by id limit 1",
                (run_id, transcript_id, client_id),
            )
        ).fetchone()
        if transcript_id
        else None
    )
    if existing:
        sid = existing[0]
    else:
        message = {
            "channel": "branch",
            "external_id": f"demo-compliance-{run_id}-{session_id}",
            "client": {"client_id": client_id},
            "text": "Проактивное обращение контроля качества: руководитель подтвердил нарушение обслуживания. Требуется устранение и ответ клиенту.",
            "timestamp": at.isoformat(),
            "geo": {"source": "none"},
            "origin": "proactive",
            "meta": {"transcript_id": transcript_id, "audio_session_id": session_id},
        }
        result = await create_signal(conn, message, source_code="api", run_id=run_id, sim_time=at, emit_event=False)
        if result.get("status") not in ("accepted", "duplicate") or not result.get("signal_id"):
            raise ValueError("Не удалось зарегистрировать проактивное обращение комплаенса")
        sid = int(result["signal_id"])
        await conn.execute("update signals set status='linked',updated_at=now() where id=%s and status='new'", (sid,))
    ar = (
        await (
            await conn.execute(
                "insert into agent_runs(kind,sim_run_id,signal_id,incident_id,prompt_version,graph_version,started_sim) values ('team_emulator',%s,%s,%s,'demo-role-v2','demo-execution-v1',%s) returning id",
                (run_id, sid, incident_id, at),
            )
        ).fetchone()
    )[0]
    ctx = ToolContext(conn, run_id=run_id, agent_run_id=ar, sim_time=at, llm_source=meta["source"])
    await link_signal_to_incident(ctx, sid, incident_id)
    deps = Deps(ctx=ctx, chain=app.state.agent.chain, profile=app.state.agent.profile)
    await deps.record_step(
        "act",
        "ok",
        {"alert_id": alert_id},
        {"demo": True, "llm_source": meta["source"], "signal_id": sid},
        reasoning="Проактивный разбор подтверждённого нарушения для конечного ответа клиенту.",
        usage=meta["usage"],
        model=meta["model"],
        latency_ms=int(meta["usage"].get("latency_ms") or 0),
    )
    await finish_run(conn, ar, meta)


async def notify_results(
    conn: Any, app: Any, run_id: int, at: dt.datetime, *, incident_ids: list[int] | None = None
) -> None:
    """Один итог на сигнал, включая дедуплицированных клиентов. Тикет = тот же инцидент."""
    rows = await (
        await conn.execute(
            "select i.id,i.status,i.resolution_summary,i.sla_breached,s.id,s.client_id,s.text,c.segment_code,c.consents,s.channel_code "
            "from incidents i join incident_signals x on x.incident_id=i.id join signals s on s.id=x.signal_id "
            "left join clients c on c.id=s.client_id where i.run_id=%s and s.run_id=%s "
            "and (%s::bigint[] is null or i.id=any(%s::bigint[])) "
            "and (i.status='closed' or exists(select 1 from team_actions ta where ta.incident_id=i.id and ta.action='escalate_ack')) "
            "and not exists(select 1 from notifications n where n.run_id=i.run_id and n.signal_id=s.id and n.template_code=case when i.status='closed' then 'resolved' else 'demo_unresolved' end) order by s.id",
            (run_id, run_id, incident_ids, incident_ids),
        )
    ).fetchall()
    svc = app.state.agent
    for iid, status, summary, _breached, sid, cid, text, segment, consents, channel in rows:
        success = status == "closed"
        from app.i18n import communication_lang

        lang = communication_lang(text or "")
        facts = str(summary or "Устранение проблемы пока не подтверждено. Обращение эскалировано, работа продолжается.")
        if lang == "en" and not success:
            facts = "The issue remains unresolved. Your case has been escalated and work continues."
        if lang == "en":
            if success:
                facts = "The demonstration check is complete. External financial actions have not been performed."
            body = facts + (" Your case is closed." if success else " Your case remains open.")
        else:
            body = (
                "Демонстрационная проверка завершена. " + facts + " Обращение закрыто."
                if success
                else facts + " Обращение остаётся открытым."
            )
        meta: dict[str, Any] = {
            "demo": True,
            "source": "mock",
            "content_source": "verified_facts",
            "model": "deterministic-customer-result",
            "provider": "mock",
            "usage": {},
            "grounded": True,
            "fallback": False,
            "prompt_version": "demo-result-v1",
        }
        arid = (
            await (
                await conn.execute(
                    "insert into agent_runs(kind,sim_run_id,signal_id,incident_id,prompt_version,graph_version,started_sim) values ('team_emulator',%s,%s,%s,'demo-result-v1','demo-execution-v1',%s) returning id",
                    (run_id, sid, iid, at),
                )
            ).fetchone()
        )[0]
        ctx = ToolContext(conn, run_id=run_id, agent_run_id=arid, sim_time=at, llm_source=meta["source"])
        await notify_client(
            ctx,
            cid,
            sid,
            iid,
            str(channel),
            "resolved" if success else "demo_unresolved",
            {"resolution": facts},
            text_override=body,
            segment=segment,
            consents=consents,
            lang=lang,
        )
        deps = Deps(ctx=ctx, chain=svc.chain, profile=svc.profile)
        await deps.record_step(
            "close" if success else "followup_monitor",
            "ok",
            {"facts": facts},
            {"demo": True, "confirmed": success, **meta},
            reasoning="Ответ по фактам команды; эмуляция сотрудника.",
            model=meta["model"],
            usage=meta["usage"],
            latency_ms=int(meta["usage"].get("latency_ms") or 0),
        )
        if success:
            await conn.execute(
                "update signals set status='closed',updated_at=now() where id=%s and run_id=%s", (sid, run_id)
            )
        await finish_run(conn, arid, meta)


async def manual_cycle(app: Any, conn: Any, rid: int, config: dict[str, Any]) -> None:
    """Событийное время ручных цепочек хранится в профиле; часы фонового банка не двигаются."""
    sim, svc = app.state.sim, app.state.agent
    if config.get("emulate_humans") and await employees(app, conn, rid, sim.clock.sim_time, manual_only=True):
        return
    # Ожидание одного клиента/оператора не блокирует другие независимые инциденты.
    rows = await (
        await conn.execute(
            "select distinct x.incident_id from incident_signals x join signals s on s.id=x.signal_id "
            "where s.run_id=%s and (s.origin='jury' or s.channel_subtype='ui_pers_demo') and not exists("
            "select 1 from incident_signals px join signals ps on ps.id=px.signal_id "
            "where px.incident_id=x.incident_id and (ps.status in ('new','processing','awaiting_human') "
            "or exists(select 1 from agent_runs a where a.signal_id=ps.id and a.kind='agent' "
            "and (a.outcome is null or a.outcome='awaiting_human'))))",
            (rid,),
        )
    ).fetchall()
    ids = [int(row[0]) for row in rows]
    if not ids:
        return
    await conn.commit()
    async with sim._lock:
        if not await execution_active(app, conn, rid, manual_only=True):
            return
        emulator = TeamEmulator(
            SimRng(sim.seed),
            conn,
            EventBus(conn),
            rid,
            demo_outcome=config["team_outcome"],
            llm=(svc.chain, svc.chain.profile_for("twin", svc.profile)),
            incident_ids=ids,
        )
        await emulator.load()
        times = dict(config.get("manual_times") or {})
        for iid in ids:
            at = max(
                sim.clock.sim_time, dt.datetime.fromisoformat(times.get(str(iid)) or sim.clock.sim_time.isoformat())
            )
            emulator.incident_ids = [iid]
            await emulator.tick(at, SimpleNamespace(active_faults=[]))
            await notify_results(conn, app, rid, at, incident_ids=[iid])
            plan = emulator.plans.get(iid)
            future = (
                [
                    step.at
                    for step in plan.steps
                    if not step.skipped and (iid, step.action, step.report_day) not in emulator.done and step.at > at
                ]
                if plan
                else []
            )
            times[str(iid)] = (min(future) if future else at).isoformat()
        config = await configuration(conn, rid)
        config["manual_times"] = times
        await save(conn, rid, config)


async def cycle(app: Any) -> None:
    sim = app.state.sim
    svc = app.state.agent
    if sim is None or svc is None or not svc.enabled:
        return
    # Публичный процесс создаёт live-run в БД; операторский процесс подхватывает его без старта часов.
    if not sim.clock.running:
        async with sim._lock:
            async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as lookup:
                row = await (
                    await lookup.execute(
                        "select r.id,r.status from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1 and r.kind='live' and r.status='paused'"
                    )
                ).fetchone()
            if row and sim.run_id != row[0]:
                sim.run_id, sim.run_status, sim.world = int(row[0]), row[1], None
    if sim.run_id is None or sim.run_status not in ("running", "paused"):
        return
    rid = sim.run_id
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        config = await configuration(conn, rid)
        if not config and getattr(sim, "full_execution", False):
            config = await ensure(conn, rid, running=sim.clock.running)
        await conn.commit()
        if config.get("enabled") and config.get("mode") == "simulation" and config.get("auto_advance"):
            await manual_cycle(app, conn, rid, config)
            await conn.commit()
            if not sim.clock.running:
                return
        if not config.get("enabled") or config.get("status") != "running" or not sim.clock.running:
            return
        if config.get("emulate_humans"):
            decided = await employees(app, conn, rid, sim.clock.sim_time)
            if decided and config.get("mode") == "demo":
                return
        # Не перемещаем время, пока агент или анализ транскрипта готовит данные.
        pending_row = await (
            await conn.execute(
                "select (select count(*) from signals where run_id=%s and status in ('new','processing')) + "
                "(select count(*) from agent_runs where sim_run_id=%s and kind='agent' and (outcome is null or outcome='awaiting_human')) + "
                "(select count(*) from transcripts where run_id=%s and status in ('received','analyzing')) + "
                "(select count(*) from incidents where run_id=%s and status='awaiting_human') + "
                "(select count(*) from compliance_alerts a join audio_sessions s on s.id=a.session_id where s.run_id=%s and a.acknowledged_at is null)",
                (rid, rid, rid, rid, rid),
            )
        ).fetchone()
        await conn.commit()
        pending = pending_row[0] if pending_row else 0
        if config.get("mode") == "demo" and (pending or svc._inflight):
            return
        failed = await (
            await conn.execute(
                "select exists(select 1 from signals where run_id=%s and status='error') "
                "or exists(select 1 from agent_runs where sim_run_id=%s and outcome='failed')",
                (rid, rid),
            )
        ).fetchone()
        if failed and failed[0] and config.get("mode") == "demo":
            sim.clock.running = False
            sim.run_status = "paused"
            await conn.execute("update sim_state set running=false where id=1 and current_run_id=%s", (rid,))
            await conn.execute("update sim_runs set status='paused' where id=%s", (rid,))
            config.update(enabled=False, status="error", error="agent_processing_failed")
            await save(conn, rid, config)
            return
        async with sim._lock:
            config = await configuration(conn, rid)
            if (
                sim.run_id != rid
                or not sim.clock.running
                or not config.get("enabled")
                or config.get("status") != "running"
            ):
                return
            next_time = sim.clock.sim_time
            bus = EventBus(conn)
            emulator = TeamEmulator(
                SimRng(sim.seed),
                conn,
                bus,
                rid,
                demo_outcome=config["team_outcome"],
                demo_context=(scenarios.get(str(config.get("scenario_id") or "")) or {}).get("demo_evidence"),
                demo_scenario_id=config.get("scenario_id"),
                llm=(svc.chain, svc.chain.profile_for("twin", svc.profile)),
            )
            await emulator.load()
            await emulator.tick(sim.clock.sim_time, SimpleNamespace(active_faults=[]))
            await notify_results(conn, app, rid, sim.clock.sim_time)
            future = [
                step.at
                for plan in emulator.plans.values()
                for step in plan.steps
                if not step.skipped
                and (plan.incident_id, step.action, step.report_day) not in emulator.done
                and step.at > sim.clock.sim_time
            ]
            if future and config.get("auto_advance") and config.get("mode") == "demo":
                at = min(future)
                # Событийный скачок: генераторы фонового банка не запускаются.
                sla = SlaEngine(conn, bus, rid)
                await sla.load()
                await sla.tick(at - dt.timedelta(minutes=15), at)
                next_time = at
                await conn.execute(
                    "update sim_state set sim_time=%s,updated_at=now() where id=1 and current_run_id=%s", (at, rid)
                )
            elif not future and config.get("mode") == "demo":
                sim.clock.running = False
                sim.run_status = "paused"
                await conn.execute("update sim_state set running=false where id=1 and current_run_id=%s", (rid,))
                await conn.execute("update sim_runs set status='paused' where id=%s", (rid,))
                config["status"] = "finished"
                config["enabled"] = False
                await save(conn, rid, config)
            await conn.commit()
            sim.clock.sim_time = next_time
        await sim._publish_tick()


async def worker(app: Any) -> None:
    while True:
        try:
            await cycle(app)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("demo_execution_failed", error_type=type(exc).__name__)
            sim = app.state.sim
            if sim is not None and sim.run_id:
                async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
                    config = await configuration(conn, sim.run_id)
                    config.update(enabled=False, status="error", error=type(exc).__name__)
                    await save(conn, sim.run_id, config)
        await asyncio.sleep(2)
