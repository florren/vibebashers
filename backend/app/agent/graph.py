"""Граф агента (T-056): узлы, рёбра, запуск прохода и возобновление после HITL. Лёгкий собственный раннер вместо LangGraph:
чекпоинт = вход шага wait_human (agent_steps.input), thread_id = agent_runs.thread_id = f"{run_id}:{signal_id}"."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any

import orjson
import psycopg

from app.agent import nodes
from app.agent.nodes import Deps
from app.agent.prompts import prompt_version
from app.agent.state import GRAPH_VERSION, AgentState, new_state
from app.agent.tools import write as wt
from app.agent.tools.base import ToolContext
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.sim.events import dumps

log = get_logger(__name__)
Node = Callable[[AgentState, Deps], Awaitable[AgentState]]

NODES: dict[str, Node] = {
    "ingest": nodes.ingest,
    "normalize": nodes.normalize,
    "identify_client": nodes.identify_client,
    "gather_context": nodes.gather_context,
    "check_rules": nodes.check_rules_node,
    "instant_decide": nodes.instant_decide,
    "act_instant": nodes.act_instant,
    "verify": nodes.verify,
    "gift": nodes.gift,
    "classify": nodes.classify,
    "decide": nodes.decide,
    "wait_human": nodes.wait_human,
    "act": nodes.act,
    "followup_monitor": nodes.followup_monitor,
    "close": nodes.close,
}
_VERIFY_READY = frozenset({"fix_deployed", "verifying", "resolved", "closed"})
GRAPH_SPEC: dict[str, Any] = {
    "version": GRAPH_VERSION,
    "nodes": [
        {"id": "ingest", "label_ru": "Приём сигнала", "label_en": "Ingest", "kind": "system"},
        {"id": "normalize", "label_ru": "Нормализация и тональность", "label_en": "Normalize", "kind": "llm"},
        {"id": "identify_client", "label_ru": "Идентификация клиента", "label_en": "Identify client", "kind": "tool"},
        {"id": "gather_context", "label_ru": "Сбор контекста", "label_en": "Gather context", "kind": "tool"},
        {"id": "check_rules", "label_ru": "Бизнес-правила", "label_en": "Check rules", "kind": "rules"},
        {"id": "instant_decide", "label_ru": "Быстрое решение", "label_en": "Instant decide", "kind": "llm"},
        {"id": "act_instant", "label_ru": "Быстрые действия", "label_en": "Act instant", "kind": "tool"},
        {"id": "gift", "label_ru": "Подарок", "label_en": "Gift", "kind": "tool"},
        {"id": "classify", "label_ru": "Классификация", "label_en": "Classify", "kind": "llm"},
        {"id": "decide", "label_ru": "Решение и политики", "label_en": "Decide", "kind": "llm"},
        {"id": "wait_human", "label_ru": "Ожидание человека (HITL)", "label_en": "Wait human", "kind": "human"},
        {"id": "act", "label_ru": "Действия (инцидент, уведомления)", "label_en": "Act", "kind": "tool"},
        {
            "id": "followup_monitor",
            "label_ru": "Follow-up / контроль SLA",
            "label_en": "Follow-up",
            "kind": "scheduled",
        },
        {"id": "verify", "label_ru": "Проверка устранения", "label_en": "Verify", "kind": "tool"},
        {"id": "close", "label_ru": "Завершение", "label_en": "Close", "kind": "system"},
    ],
    "edges": [
        {"from": "ingest", "to": "normalize"},
        {"from": "normalize", "to": "identify_client"},
        {"from": "identify_client", "to": "gather_context"},
        {"from": "gather_context", "to": "check_rules"},
        {"from": "check_rules", "to": "instant_decide", "condition": "fast_path"},
        {"from": "check_rules", "to": "classify", "condition": "!fast_path"},
        {"from": "instant_decide", "to": "act_instant"},
        {"from": "act_instant", "to": "verify"},
        {"from": "verify", "to": "gift"},
        {"from": "verify", "to": "followup_monitor", "condition": "verify reopen"},
        {"from": "gift", "to": "close"},
        {"from": "classify", "to": "decide"},
        {"from": "decide", "to": "wait_human", "condition": "needs_human"},
        {"from": "decide", "to": "act", "condition": "!needs_human"},
        {"from": "wait_human", "to": "act", "condition": "human decided"},
        {"from": "act", "to": "followup_monitor", "condition": "followup scheduled"},
        {"from": "act", "to": "close", "condition": "!followup scheduled"},
        {"from": "followup_monitor", "to": "verify", "condition": "wake"},
        {"from": "followup_monitor", "to": "close", "condition": "!followup"},
    ],
}


async def load_deps(
    conn: psycopg.AsyncConnection[Any],
    *,
    chain: ProviderChain,
    profile: LLMProfile,
    run_id: int,
    agent_run_id: int,
    sim_time: dt.datetime,
) -> Deps:
    ctx = ToolContext(conn, run_id=run_id, agent_run_id=agent_run_id, sim_time=sim_time)
    teams = [r[0] for r in await (await conn.execute("select code from teams order by code")).fetchall()]
    rules = [
        (int(r[0]), dict(r[1] or {}), list(r[2] or []))
        for r in await (
            await conn.execute("select id, match, team_codes from routing_rules order by priority")
        ).fetchall()
    ]
    matrix = {
        (r[0], r[1]): {"fix_days": r[2], "report_days": list(r[3] or []), "take_hours": r[4]}
        for r in await (
            await conn.execute("select complexity, criticality, fix_days, report_days, take_hours from sla_matrix")
        ).fetchall()
    }
    pol_row = await (await conn.execute("select value from settings where key = 'policies'")).fetchone()
    fewshot = [
        {
            "signal": r[0],
            "decision": r[1],
            "comment": r[2],
            "signal_type": r[3],
            "product": r[4],
            "system": r[5],
        }
        for r in await (
            await conn.execute(
                "select left(s.text, 200), hd.decision, hd.comment, s.classification->>'signal_type', "
                "s.classification->>'product', s.classification->>'system' "
                "from human_decisions hd join signals s on s.id = hd.signal_id "
                "where hd.use_as_fewshot and hd.decision is not null order by hd.decided_at desc limit 5"
            )
        ).fetchall()
    ]
    return Deps(
        ctx=ctx,
        chain=chain,
        profile=profile,
        policies=dict(pol_row[0] or {}) if pol_row else {},
        teams=teams,
        routing_rules=rules,
        sla_matrix=matrix or None,
        fewshot=fewshot,
    )


async def _load_signal(conn: psycopg.AsyncConnection[Any], signal_id: int) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select id, run_id, channel_code, channel_subtype, client_id, external_contact, text, received_sim, origin, geo, source_operation_id, source_fault_id, parent_signal_id, status, external_post_id, red_words, flags, meta from signals where id = %s",
        (signal_id,),
    )
    r = await cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "run_id": r[1],
        "channel": r[2],
        "channel_subtype": r[3],
        "client_id": r[4],
        "external_contact": r[5],
        "text": r[6],
        "received_sim": r[7].isoformat() if r[7] else None,
        "origin": r[8],
        "geo": r[9],
        "source_operation_id": r[10],
        "source_fault_id": r[11],
        "parent_signal_id": r[12],
        "status": r[13],
        "external_post_id": r[14],
        "red_words": r[15],
        "flags": r[16],
        "meta": r[17],
    }


async def _finish(
    conn: psycopg.AsyncConnection[Any], deps: Deps, state: AgentState, outcome: str, error: str | None = None
) -> None:
    await conn.execute(
        "update agent_runs set finished_at = case when %s in ('awaiting_human','deferred') then null else now() end, outcome = %s, needed_human = needed_human or %s, total_tokens = %s, prompt_tokens = %s, completion_tokens = %s, total_latency_ms = %s, cost_estimate = %s, error = %s, client_id = coalesce(client_id, %s) where id = %s",
        (
            outcome,
            outcome,
            outcome == "awaiting_human",
            deps.tokens["prompt"] + deps.tokens["completion"],
            deps.tokens["prompt"],
            deps.tokens["completion"],
            deps.tokens["latency_ms"],
            round(float(deps.tokens.get("cost", 0)), 6),
            error,
            (state.get("client") or {}).get("client_id"),
            deps.ctx.agent_run_id,
        ),
    )
    await deps.ctx.notify(
        "agent",
        "run_finished",
        {
            "agent_run_id": deps.ctx.agent_run_id,
            "signal_id": state["signal"]["id"],
            "outcome": outcome,
            "incident_id": next(
                (a.get("incident_id") for a in state.get("actions") or [] if a.get("incident_id")), None
            ),
            "needed_human": outcome == "awaiting_human",
            "signal_type": state.get("classification", {}).get("signal_type"),
        },
    )


async def run_graph(state: AgentState, deps: Deps, conn: psycopg.AsyncConnection[Any]) -> AgentState:
    """Исполняет узлы от state.current_node до close или остановки на wait_human. Каждый узел — своя транзакция."""
    node = state.get("current_node") or "ingest"
    while True:
        fn = NODES.get(node)
        if fn is None:
            raise RuntimeError(f"узел {node} не найден")
        try:
            await deps.begin_step(node)
            await conn.commit()
            state = await fn(state, deps)
            await conn.commit()
        except Exception as exc:
            await conn.rollback()
            log.exception("agent_node_failed", node=node, signal_id=state["signal"]["id"])
            state["errors"].append(f"{node}: {type(exc).__name__}: {str(exc)[:200]}")
            try:
                await deps.record_step(
                    node,
                    "error",
                    {"node": node},
                    {"error": state["errors"][-1]},
                    reasoning=f"Ошибка узла {node}; проход завершён с failed.",
                )
                await conn.execute(
                    "update signals set status = 'error', updated_at = now() where id = %s", (state["signal"]["id"],)
                )
                await _finish(conn, deps, state, "failed", state["errors"][-1])
                await conn.commit()
            except Exception:  # noqa: BLE001
                await conn.rollback()
            state["outcome"] = "failed"
            return state
        if node == "wait_human" and state.get("outcome") == "awaiting_human":
            await _finish(conn, deps, state, "awaiting_human")
            await conn.commit()
            return state
        if node == "followup_monitor" and state.get("outcome") == "deferred":
            await _finish(conn, deps, state, "deferred")
            await conn.commit()
            return state
        if node == "close":
            await _finish(conn, deps, state, state.get("outcome") or "completed")
            await conn.commit()
            return state
        node = state["current_node"]


async def process_signal(
    conn: psycopg.AsyncConnection[Any],
    *,
    signal_id: int,
    chain: ProviderChain,
    profile: LLMProfile,
    sim_time: dt.datetime | None = None,
) -> AgentState | None:
    """Полный проход по сигналу: создаёт agent_runs и исполняет граф. Повторный вызов для уже обработанного сигнала — no-op."""
    sig = await _load_signal(conn, signal_id)
    if not sig:
        return None
    dup = await (
        await conn.execute(
            "select id from agent_runs where signal_id = %s and kind = 'agent' and outcome is distinct from 'failed'",
            (signal_id,),
        )
    ).fetchone()
    if dup:
        return None
    sim_time = sim_time or (
        dt.datetime.fromisoformat(sig["received_sim"]) if sig["received_sim"] else dt.datetime.now(dt.UTC)
    )
    pv = prompt_version()
    profile_row = await (
        await conn.execute(
            "select id, price_in_per_1m, price_out_per_1m from llm_profiles where code = %s",
            (profile.code,),
        )
    ).fetchone()
    if profile_row is None:
        profile_row = await (
            await conn.execute(
                "select id, price_in_per_1m, price_out_per_1m from llm_profiles where provider = %s and model = %s order by id limit 1",
                (profile.provider, profile.model),
            )
        ).fetchone()
    llm_profile_id = int(profile_row[0]) if profile_row else None
    if (
        profile_row
        and profile.price_in_per_1m == 0
        and profile.price_out_per_1m == 0
        and (float(profile_row[1] or 0) or float(profile_row[2] or 0))
    ):
        profile = dataclasses.replace(
            profile,
            price_in_per_1m=float(profile_row[1] or 0),
            price_out_per_1m=float(profile_row[2] or 0),
        )
    row = await (
        await conn.execute(
            "insert into agent_runs (kind, sim_run_id, signal_id, client_id, llm_profile_id, prompt_version, graph_version, thread_id, started_sim) values ('agent', %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (
                sig["run_id"],
                signal_id,
                sig["client_id"],
                llm_profile_id,
                pv,
                GRAPH_VERSION,
                f"{sig['run_id']}:{signal_id}",
                sim_time,
            ),
        )
    ).fetchone()
    agent_run_id = int(row[0])  # type: ignore[index]
    await conn.commit()
    deps = await load_deps(
        conn, chain=chain, profile=profile, run_id=int(sig["run_id"]), agent_run_id=agent_run_id, sim_time=sim_time
    )
    state = new_state(int(sig["run_id"]), sig, agent_run_id, pv)
    await deps.ctx.notify(
        "agent", "run_started", {"agent_run_id": agent_run_id, "signal_id": signal_id, "client_id": sig["client_id"]}
    )
    return await run_graph(state, deps, conn)


async def resume_after_followup(
    conn: psycopg.AsyncConnection[Any],
    *,
    followup_id: int,
    chain: ProviderChain,
    profile: LLMProfile,
    sim_time: dt.datetime | None = None,
) -> AgentState | None:
    """Возобновление после срабатывания followup: чекпоинт — input шага followup_monitor."""
    row = await (
        await conn.execute(
            "select f.agent_run_id, f.signal_id, f.incident_id, f.reason, f.payload, f.status, ar.sim_run_id, "
            "(select input from agent_steps st where st.run_id = f.agent_run_id and st.node = 'followup_monitor' "
            "order by st.seq desc limit 1), "
            "(select count(*) from agent_steps st where st.run_id = f.agent_run_id) "
            "from followups f join agent_runs ar on ar.id = f.agent_run_id where f.id = %s",
            (followup_id,),
        )
    ).fetchone()
    if not row or row[7] is None:
        return None
    agent_run_id, signal_id, incident_id, reason, payload, _fstatus, run_id, checkpoint, nsteps = row
    reason = str(reason)
    if reason == "escalation_check":
        return None
    state: AgentState = orjson.loads(dumps(checkpoint))
    sim_time = sim_time or dt.datetime.now(dt.UTC)
    deps = await load_deps(
        conn, chain=chain, profile=profile, run_id=int(run_id), agent_run_id=int(agent_run_id), sim_time=sim_time
    )
    deps.steps = [{"seq": i + 1, "node": "?", "status": "ok"} for i in range(int(nsteps))]
    sig = await _load_signal(conn, int(signal_id))
    if sig:
        state["signal"] = sig
    await conn.execute(
        "update agent_runs set outcome = null, finished_at = null, error = null where id = %s", (agent_run_id,)
    )
    payload = dict(payload or {})

    if reason == "awaiting_client":
        child = await (
            await conn.execute("select id from signals where parent_signal_id = %s limit 1", (signal_id,))
        ).fetchone()
        if child:
            await conn.execute(
                "update signals set status = 'answered', updated_at = now() where id = %s and status in ('deferred','awaiting_client')",
                (signal_id,),
            )
            state["outcome"] = None
            state["current_node"] = "verify"
        else:
            c = state.get("classification") or {}
            escalate = (state.get("decision") or {}).get("escalate_on_silence")
            if escalate is None:
                escalate = c.get("signal_type") == "fraud_suspicion"
            if escalate and incident_id:
                await wt.escalate_to_manager(
                    deps.ctx,
                    int(signal_id),
                    int(incident_id),
                    "Клиент не предоставил данные в срок",
                    "high",
                    "cx_lead",
                )
            await conn.execute("update signals set status = 'closed', updated_at = now() where id = %s", (signal_id,))
            state["verified"] = True
            state["outcome"] = "completed"
            state["current_node"] = "close"
            await deps.record_step(
                "followup_monitor",
                "ok",
                dict(state),
                {"reason": reason, "escalated": bool(escalate)},
                reasoning="Тишина клиента: эскалация и закрытие сигнала.",
            )
            await _finish(conn, deps, state, "completed")
            await conn.commit()
            return state
    elif reason == "report_due" and incident_id:
        d = state.get("decision") or {}
        team = str((d.get("route") or {}).get("team") or "team_cx")
        await wt.create_task(deps.ctx, "report_reminder", int(incident_id), None, {"incident_id": int(incident_id)})
        await wt.notify_team(
            deps.ctx,
            team,
            int(incident_id),
            int(signal_id),
            "Требуется промежуточный отчёт по SLA",
            {"incident_id": incident_id},
        )
        wake_h = float(payload.get("wake_in_sim_hours") or 4.0)
        await conn.execute(
            "insert into followups (sim_run_id, agent_run_id, signal_id, incident_id, wake_sim, reason, payload, status) "
            "values (%s, %s, %s, %s, %s, %s, %s::jsonb, 'scheduled')",
            (
                int(run_id),
                int(agent_run_id),
                int(signal_id),
                int(incident_id),
                sim_time + dt.timedelta(hours=wake_h),
                reason,
                dumps({**payload, "wake_in_sim_hours": wake_h}),
            ),
        )
        state["outcome"] = "deferred"
        state["current_node"] = "followup_monitor"
        await conn.commit()
        return await run_graph(state, deps, conn)
    elif reason in ("awaiting_team", "verify_fix"):
        inc_st = None
        if incident_id:
            st_row = await deps.ctx.fetchone("select status from incidents where id = %s", (int(incident_id),))
            inc_st = str(st_row[0]) if st_row else None
        if inc_st in _VERIFY_READY:
            state["outcome"] = None
            state["current_node"] = "verify"
        else:
            wake_h = float(payload.get("wake_in_sim_hours") or 4.0)
            await conn.execute(
                "insert into followups (sim_run_id, agent_run_id, signal_id, incident_id, wake_sim, reason, payload, status) "
                "values (%s, %s, %s, %s, %s, %s, %s::jsonb, 'scheduled')",
                (
                    int(run_id),
                    int(agent_run_id),
                    int(signal_id),
                    int(incident_id) if incident_id else None,
                    sim_time + dt.timedelta(hours=wake_h),
                    reason,
                    dumps({**payload, "wake_in_sim_hours": wake_h}),
                ),
            )
            state["outcome"] = "deferred"
            state["current_node"] = "followup_monitor"
    else:
        state["outcome"] = None
        state["current_node"] = "verify"

    await conn.commit()
    return await run_graph(state, deps, conn)


async def wake_due_followups(
    conn: psycopg.AsyncConnection[Any],
    *,
    sim_time: dt.datetime,
    chain: ProviderChain,
    profile: LLMProfile,
) -> int:
    """Атомарно помечает просроченные followups как fired и возобновляет соответствующие прогоны."""
    rows = await (
        await conn.execute(
            "with due as (select id from followups where status = 'scheduled' and wake_sim <= %s "
            "and agent_run_id is not null and signal_id is not null for update skip locked) "
            "update followups f set status = 'fired' from due where f.id = due.id returning f.id",
            (sim_time,),
        )
    ).fetchall()
    resumed = 0
    for (fid,) in rows:
        await conn.commit()
        st = await resume_after_followup(conn, followup_id=int(fid), chain=chain, profile=profile, sim_time=sim_time)
        if st is not None:
            resumed += 1
    return resumed


async def wake_followups_for_incident(
    conn: psycopg.AsyncConnection[Any],
    *,
    incident_id: int,
    sim_time: dt.datetime,
    chain: ProviderChain,
    profile: LLMProfile,
) -> int:
    await conn.execute(
        "update followups set wake_sim = %s where incident_id = %s and status = 'scheduled' "
        "and reason is distinct from 'awaiting_client'",
        (sim_time, incident_id),
    )
    await conn.commit()
    return await wake_due_followups(conn, sim_time=sim_time, chain=chain, profile=profile)


async def expire_hitl(
    conn: psycopg.AsyncConnection[Any],
    *,
    sim_time: dt.datetime,
    chain: ProviderChain,
    profile: LLMProfile,
) -> None:
    """Просроченные HITL: эскалация cx_lead при наличии team_cx, иначе безопасный modify+resume."""
    pol_row = await (await conn.execute("select value from settings where key = 'policies'")).fetchone()
    policies = dict(pol_row[0] or {}) if pol_row else {}
    wait_h = float(policies.get("hitl_wait_sim_hours") or 2)
    cutoff = sim_time - dt.timedelta(hours=wait_h)
    rows = await (
        await conn.execute(
            "select hd.id, hd.agent_run_id, hd.signal_id, hd.incident_id, ar.sim_run_id from human_decisions hd "
            "join agent_runs ar on ar.id = hd.agent_run_id where hd.decision is null and hd.requested_sim <= %s",
            (cutoff,),
        )
    ).fetchall()
    if not rows:
        return
    escalate = policies.get("hitl_timeout_escalate", True)
    cx_row = await (await conn.execute("select 1 from teams where code = 'team_cx' limit 1")).fetchone()
    has_cx = bool(escalate and cx_row)
    timeout_proposal = dumps({"gift": None, "client_action": {"kind": "acknowledge"}})
    for hid, agent_run_id, signal_id, incident_id, run_id in rows:
        if has_cx:
            ctx = ToolContext(conn, run_id=int(run_id), agent_run_id=int(agent_run_id), sim_time=sim_time)
            await wt.escalate_to_manager(
                ctx,
                int(signal_id),
                int(incident_id) if incident_id else None,
                "Таймаут ожидания решения оператора (HITL)",
                "high",
                "cx_lead",
            )
            await conn.commit()
            continue
        await conn.execute(
            "update human_decisions set decision = 'modify', modified_proposal = %s::jsonb, decided_by = 'timeout', "
            "decided_sim = %s, decided_at = now(), use_as_fewshot = false where id = %s and decision is null",
            (timeout_proposal, sim_time, hid),
        )
        await conn.commit()
        await resume_after_human(conn, human_decision_id=int(hid), chain=chain, profile=profile, sim_time=sim_time)


async def resume_after_human(
    conn: psycopg.AsyncConnection[Any],
    *,
    human_decision_id: int,
    chain: ProviderChain,
    profile: LLMProfile,
    sim_time: dt.datetime | None = None,
) -> AgentState | None:
    """Возобновление после решения оператора: чекпоинт — input шага wait_human; шаги продолжают нумерацию."""
    row = await (
        await conn.execute(
            "select hd.agent_run_id, hd.decision, hd.modified_proposal, ar.sim_run_id, (select input from agent_steps where run_id = hd.agent_run_id and node = 'wait_human' order by seq desc limit 1), (select count(*) from agent_steps where run_id = hd.agent_run_id) from human_decisions hd join agent_runs ar on ar.id = hd.agent_run_id where hd.id = %s and hd.decision is not null",
            (human_decision_id,),
        )
    ).fetchone()
    if not row or not row[4]:
        return None
    agent_run_id, decision, modified, run_id, checkpoint, nsteps = row
    state: AgentState = orjson.loads(dumps(checkpoint))
    sim_time = sim_time or dt.datetime.now(dt.UTC)
    deps = await load_deps(
        conn, chain=chain, profile=profile, run_id=int(run_id), agent_run_id=int(agent_run_id), sim_time=sim_time
    )
    budget_row = await (
        await conn.execute(
            "select coalesce(sum(octet_length(coalesce(prompt,'')) + octet_length(coalesce(response_raw,'')) + "
            "octet_length(coalesce(reasoning,'')) + octet_length(coalesce(output::text,'')) + "
            "octet_length(coalesce(tool_calls::text,''))), 0) from agent_steps where run_id = %s",
            (agent_run_id,),
        )
    ).fetchone()
    deps.text_bytes_used = int(budget_row[0]) if budget_row else 0
    deps.steps = [{"seq": i + 1, "node": "?", "status": "ok"} for i in range(int(nsteps))]
    state = nodes.apply_human_decision(state, str(decision), dict(modified or {}))
    await deps.record_step(
        "wait_human",
        "ok",
        {"human_decision_id": human_decision_id},
        {"decision": decision, "modified": modified},
        reasoning=f"Решение человека: {decision}. Продолжаем выполнение.",
    )
    await conn.commit()
    return await run_graph(state, deps, conn)
