"""Runtime boundary утверждённой policy; run marker и producers без model writes."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from app.agent.tools.base import StateEvidenceSink
from app.sim.behavior.policy import DemoPolicy
from app.sim.behavior.store import BehaviorStore, record_agent_state_intent

POLICY_PATH = Path(__file__).resolve().parents[4] / "data/behavior/demo_policy.review.yaml"


def configured_policy() -> DemoPolicy | None:
    policy = DemoPolicy.load(POLICY_PATH, validation_only=True)
    return policy if policy.spec["enabled"] else None


async def effective_policy(
    conn: psycopg.AsyncConnection[Any], run_id: int | None, policy: DemoPolicy | None
) -> DemoPolicy | None:
    """Policy применима только к фактическому free/scenario, без отключения loader."""
    if policy is None or run_id is None:
        return None
    run = await BehaviorStore(conn)._one("select kind from sim_runs where id=%s", (run_id,))
    if run is None:
        raise ValueError("behavior run отсутствует")
    return policy if run[0] in ("free", "scenario") else None


async def prepare_run(conn: psycopg.AsyncConnection[Any], run_id: int, at: dt.datetime, policy: DemoPolicy) -> None:
    store = BehaviorStore(conn)
    store.require_transaction()
    row = await store._one("select kind,status from sim_runs where id=%s for share", (run_id,))
    if row is None or row[0] not in ("free", "scenario") or row[1] not in ("running", "paused", "interrupted"):
        raise ValueError("behavior требует открытый free/scenario run")
    marker = await store._one("select policy_hash from behavior_runs where run_id=%s", (run_id,))
    if marker:
        if marker[0] != policy.sha256:
            raise ValueError("behavior policy изменена: создайте новый run, текущий hash закреплён")
        return
    legacy = await store._one(
        "select exists(select 1 from operations where run_id=%s) or exists(select 1 from signals where run_id=%s) "
        "or exists(select 1 from faults where run_id=%s) or exists(select 1 from client_states where run_id=%s) "
        "or exists(select 1 from sim_events where run_id=%s) or exists(select 1 from notifications where run_id=%s) "
        "or exists(select 1 from incidents where run_id=%s) or exists(select 1 from client_reactions where run_id=%s) "
        "or exists(select 1 from agent_runs where sim_run_id=%s)",
        (run_id,) * 9,
    )
    if legacy and legacy[0]:
        raise ValueError("Legacy run без behavior marker содержит историю/неизвестные timers: создайте новый run")
    await conn.execute(
        "insert into behavior_runs(run_id,policy_hash,activated_sim) values(%s,%s,%s)", (run_id, policy.sha256, at)
    )


async def require_run(conn: psycopg.AsyncConnection[Any], run_id: int, *, policy: DemoPolicy | None = None) -> None:
    """Read-only admission до graph/control effects; legacy историю не угадывает."""
    policy = policy if policy is not None else configured_policy()
    if policy is None:
        return
    store = BehaviorStore(conn)
    run = await store._one("select kind,status from sim_runs where id=%s", (run_id,))
    if run is None:
        raise ValueError("behavior run отсутствует")
    if run[0] not in ("free", "scenario"):
        return
    current = await store._one("select current_run_id from sim_state where id=1", ())
    if run[1] not in ("running", "paused", "interrupted") or not current or current[0] != run_id:
        return
    marker = await store._one("select policy_hash from behavior_runs where run_id=%s", (run_id,))
    if marker is not None:
        if marker[0] != policy.sha256:
            raise ValueError("behavior policy изменена: создайте новый run")
        return
    legacy = await store._one(
        "select exists(select 1 from operations where run_id=%s) or exists(select 1 from signals where run_id=%s) "
        "or exists(select 1 from faults where run_id=%s) or exists(select 1 from client_states where run_id=%s) "
        "or exists(select 1 from sim_events where run_id=%s) or exists(select 1 from notifications where run_id=%s) "
        "or exists(select 1 from incidents where run_id=%s) or exists(select 1 from client_reactions where run_id=%s) "
        "or exists(select 1 from agent_runs where sim_run_id=%s)",
        (run_id,) * 9,
    )
    if legacy and legacy[0]:
        raise ValueError("Legacy run без behavior marker содержит историю/неизвестные timers: создайте новый run")


async def state_sink(conn: psycopg.AsyncConnection[Any], run_id: int) -> StateEvidenceSink | None:
    policy = configured_policy()
    if await effective_policy(conn, run_id, policy) is None:
        return None
    await require_run(conn, run_id)
    # Включая inactive legacy без marker: None разрешил бы legacy state UPDATE.
    return record_agent_state_intent


async def twin_sink(conn: psycopg.AsyncConnection[Any], run_id: int, reaction_id: int) -> bool:
    policy = configured_policy()
    if await effective_policy(conn, run_id, policy) is None:
        return False
    store = BehaviorStore(conn)
    if not await store.active_run(run_id):
        return True  # Подавлено; legacy Twin care writer также не запускается.
    await require_run(conn, run_id)
    await store.enqueue_twin(run_id=run_id, reaction_id=reaction_id)
    return True


async def _rows(conn: psycopg.AsyncConnection[Any], query: str, args: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(query, args)
        return list(await cur.fetchall())


async def capture(conn: psycopg.AsyncConnection[Any], run_id: int) -> None:
    """Native durable facts закрывают LISTEN/restart gap; нет внешней private queue."""
    store = BehaviorStore(conn)
    store.require_transaction()
    # Op факты сохраняются в producer TX; fallback захватывает уже записанный op
    # после process restart, но не переигрывает legacy run без marker.
    rows = await _rows(
        conn,
        "select o.id from operations o where o.run_id=%s and o.status='failed' and not exists(select 1 from behavior_evidence e where e.run_id=o.run_id and e.client_id=o.client_id and e.source_kind='operation' and e.source_id=o.id) order by o.started_sim,o.id",
        (run_id,),
    )
    for row in rows:
        await store.enqueue_operation(run_id=run_id, operation_id=row[0])
    rows = await _rows(
        conn,
        "select n.id from notifications n where (exists(select 1 from operations o where o.run_id=n.run_id and o.client_id=n.client_id and o.status='failed') "
        "or exists(select 1 from behavior_runtime b where b.run_id=n.run_id and b.client_id=n.client_id) "
        "or exists(select 1 from behavior_agent_intents x where x.run_id=n.run_id and x.client_id=n.client_id)) "
        "and n.run_id=%s and n.status in ('sent','delivered') and n.recipient_type in ('client','public') "
        "and not exists(select 1 from behavior_evidence e where e.run_id=n.run_id and e.client_id=n.client_id and e.source_kind='notification' and e.source_id=n.id) order by n.sent_sim,n.id",
        (run_id,),
    )
    for row in rows:
        await store.enqueue_notification(run_id=run_id, notification_id=row[0])
    rows = await _rows(
        conn,
        "select c.id from client_reactions c where (exists(select 1 from operations o where o.run_id=c.run_id and o.client_id=c.client_id and o.status='failed') "
        "or exists(select 1 from behavior_runtime b where b.run_id=c.run_id and b.client_id=c.client_id) "
        "or exists(select 1 from behavior_agent_intents x where x.run_id=c.run_id and x.client_id=c.client_id)) "
        "and c.run_id=%s and not exists(select 1 from behavior_evidence e where e.run_id=c.run_id and e.client_id=c.client_id and e.source_kind='twin_reaction' and e.source_id=c.id) order by c.reacted_sim,c.id",
        (run_id,),
    )
    for row in rows:
        await store.enqueue_twin(run_id=run_id, reaction_id=row[0])
    # Одна actual cause join вместо cross product всех clients/incidents. Также
    # работает в первом tick до появления runtime, не теряя ранний SLA fact.
    cause = (
        " from operations o join incidents i on i.run_id=o.run_id and ("
        "(o.fault_id is not null and i.fault_id=o.fault_id) or exists("
        "select 1 from incident_signals x join signals s on s.id=x.signal_id "
        "where x.incident_id=i.id and s.run_id=o.run_id and s.client_id=o.client_id "
        "and (s.source_operation_id=o.id or (o.fault_id is not null and s.source_fault_id=o.fault_id)))) "
    )
    rows = await _rows(
        conn,
        "select distinct o.client_id,e.id,e.sim_time"
        + cause
        + "join sim_events e on e.run_id=i.run_id and e.payload->>'incident_id'=i.id::text "
        "where o.run_id=%s and o.status='failed' and e.event_type in ('sla.breached','sla.report_missing','sla.first_response_overdue') "
        "and not exists(select 1 from behavior_evidence x where x.run_id=o.run_id and x.client_id=o.client_id and x.source_kind='sla' and x.source_id=e.id) order by e.sim_time,e.id,o.client_id",
        (run_id,),
    )
    for client, event, at in rows:
        await store._enqueue(run_id, client, "sla", event, at)
    rows = await _rows(
        conn,
        "select distinct o.client_id,i.id,coalesce(i.resolved_sim,i.closed_sim) at"
        + cause
        + "where o.run_id=%s and o.status='failed' and i.status in ('resolved','closed') and coalesce(i.resolved_sim,i.closed_sim) is not null "
        "and not exists(select 1 from behavior_evidence x where x.run_id=o.run_id and x.client_id=o.client_id and x.source_kind='resolution' and x.source_id=i.id) order by at,i.id,o.client_id",
        (run_id,),
    )
    for client, incident, at in rows:
        await store._enqueue(run_id, client, "resolution", incident, at)

    # Already-complained signal cause не получает выдуманный operation FK.
    signal_cause = (
        " from behavior_runtime b join behavior_receipts r on r.run_id=b.run_id and r.client_id=b.client_id "
        "and r.source_kind='signal' and r.action='cause:'||b.episode_no::text "
        "join signals s on s.id=r.source_id and s.run_id=b.run_id and s.client_id=b.client_id "
        "join incident_signals x on x.signal_id=s.id join incidents i on i.id=x.incident_id and i.run_id=b.run_id "
    )
    rows = await _rows(
        conn,
        "select distinct b.client_id,e.id,e.sim_time"
        + signal_cause
        + "join sim_events e on e.run_id=i.run_id and e.payload->>'incident_id'=i.id::text "
        "where b.run_id=%s and e.event_type in ('sla.breached','sla.report_missing','sla.first_response_overdue') "
        "and not exists(select 1 from behavior_evidence q where q.run_id=b.run_id and q.client_id=b.client_id and q.source_kind='sla' and q.source_id=e.id) order by e.sim_time,e.id,b.client_id",
        (run_id,),
    )
    for client, event, at in rows:
        await store._enqueue(run_id, client, "sla", event, at)
    rows = await _rows(
        conn,
        "select distinct b.client_id,i.id,coalesce(i.resolved_sim,i.closed_sim) at"
        + signal_cause
        + "where b.run_id=%s and i.status in ('resolved','closed') and coalesce(i.resolved_sim,i.closed_sim) is not null "
        "and not exists(select 1 from behavior_evidence q where q.run_id=b.run_id and q.client_id=b.client_id and q.source_kind='resolution' and q.source_id=i.id) order by at,i.id,b.client_id",
        (run_id,),
    )
    for client, incident, at in rows:
        await store._enqueue(run_id, client, "resolution", incident, at)


async def capture_signal_case(conn: psycopg.AsyncConnection[Any], run: int, client: int, signal: int) -> None:
    """Новая signal membership видит уже committed SLA/resolution до hazard draw."""
    store = BehaviorStore(conn)
    store.require_transaction()
    rows = await _rows(
        conn,
        "with recursive lineage as (select id,parent_signal_id,array[id] path,1 depth from signals where id=%s and run_id=%s and client_id=%s "
        "union all select p.id,p.parent_signal_id,l.path||p.id,l.depth+1 from lineage l join signals p on p.id=l.parent_signal_id "
        "where p.run_id=%s and p.client_id=%s and l.depth<64 and not p.id=any(l.path)) "
        "select distinct i.id,i.status,coalesce(i.resolved_sim,i.closed_sim) at from lineage l "
        "join incident_signals x on x.signal_id=l.id join incidents i on i.id=x.incident_id where i.run_id=%s order by i.id",
        (signal, run, client, run, client, run),
    )
    for incident, status, at in rows:
        if status in ("resolved", "closed") and at is not None:
            await store._enqueue(run, client, "resolution", incident, at)
        events = await _rows(
            conn,
            "select id,sim_time from sim_events where run_id=%s and payload->>'incident_id'=%s "
            "and event_type in ('sla.breached','sla.report_missing','sla.first_response_overdue') order by sim_time,id",
            (run, str(incident)),
        )
        for event, stamp in events:
            await store._enqueue(run, client, "sla", event, stamp)
