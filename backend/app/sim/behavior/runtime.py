"""Runtime boundary утверждённой policy; run marker и producers без model writes."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg

from app.agent.tools.base import StateEvidenceSink
from app.sim.behavior.policy import DemoPolicy
from app.sim.behavior.store import BehaviorStore, record_agent_state_intent

POLICY_PATH = Path(__file__).resolve().parents[4] / "data/behavior/demo_policy.review.yaml"


def configured_policy() -> DemoPolicy | None:
    policy = DemoPolicy.load(POLICY_PATH, validation_only=True)
    return policy if policy.spec["enabled"] else None


async def prepare_run(conn: psycopg.AsyncConnection[Any], run_id: int, at: dt.datetime, policy: DemoPolicy) -> None:
    store = BehaviorStore(conn)
    store.require_transaction()
    row = await store._one("select kind,status from sim_runs where id=%s for update", (run_id,))
    if row is None or row[0] not in ("free", "scenario") or row[1] not in ("running", "paused", "interrupted"):
        raise ValueError("behavior требует открытый free/scenario run")
    marker = await store._one("select policy_hash from behavior_runs where run_id=%s", (run_id,))
    if marker:
        if marker[0] != policy.sha256:
            raise ValueError("behavior policy изменена: создайте новый run, текущий hash закреплён")
        return
    legacy = await store._one(
        "select exists(select 1 from operations where run_id=%s) or exists(select 1 from signals where run_id=%s) "
        "or exists(select 1 from faults where run_id=%s) or exists(select 1 from client_states where run_id=%s)",
        (run_id, run_id, run_id, run_id),
    )
    if legacy and legacy[0]:
        raise ValueError("Legacy run без behavior marker содержит историю/неизвестные timers: создайте новый run")
    await conn.execute(
        "insert into behavior_runs(run_id,policy_hash,activated_sim) values(%s,%s,%s)", (run_id, policy.sha256, at)
    )


async def state_sink(conn: psycopg.AsyncConnection[Any], run_id: int) -> StateEvidenceSink | None:
    if configured_policy() is None:
        return None
    row = await BehaviorStore(conn)._one("select 1 from behavior_runs where run_id=%s", (run_id,))
    return record_agent_state_intent if row else None


async def twin_sink(conn: psycopg.AsyncConnection[Any], run_id: int, reaction_id: int) -> bool:
    row = await BehaviorStore(conn)._one("select 1 from behavior_runs where run_id=%s", (run_id,))
    if row is None:
        return False
    await BehaviorStore(conn).enqueue_twin(run_id=run_id, reaction_id=reaction_id)
    return True


async def capture(conn: psycopg.AsyncConnection[Any], run_id: int) -> None:
    """Native durable facts закрывают LISTEN/restart gap; нет внешней private queue."""
    store = BehaviorStore(conn)
    store.require_transaction()
    # Op факты сохраняются в producer TX; fallback захватывает уже записанный op
    # после process restart, но не переигрывает legacy run без marker.
    rows = await conn.execute(
        "select o.id from operations o where o.run_id=%s and o.status='failed' and not exists(select 1 from behavior_evidence e where e.run_id=o.run_id and e.client_id=o.client_id and e.source_kind='operation' and e.source_id=o.id) order by o.started_sim,o.id",
        (run_id,),
    )
    for row in await rows.fetchall():
        await store.enqueue_operation(run_id=run_id, operation_id=row[0])
    rows = await conn.execute(
        "select n.id from notifications n where exists(select 1 from operations o where o.run_id=n.run_id and o.client_id=n.client_id and o.status='failed') "
        "and n.run_id=%s and n.status in ('sent','delivered') and n.recipient_type in ('client','public') "
        "and not exists(select 1 from behavior_evidence e where e.run_id=n.run_id and e.client_id=n.client_id and e.source_kind='notification' and e.source_id=n.id) order by n.sent_sim,n.id",
        (run_id,),
    )
    for row in await rows.fetchall():
        await store.enqueue_notification(run_id=run_id, notification_id=row[0])
    rows = await conn.execute(
        "select c.id from client_reactions c where exists(select 1 from operations o where o.run_id=c.run_id and o.client_id=c.client_id and o.status='failed') "
        "and c.run_id=%s and not exists(select 1 from behavior_evidence e where e.run_id=c.run_id and e.client_id=c.client_id and e.source_kind='twin_reaction' and e.source_id=c.id) order by c.reacted_sim,c.id",
        (run_id,),
    )
    for row in await rows.fetchall():
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
    rows = await conn.execute(
        "select distinct o.client_id,e.id,e.sim_time"
        + cause
        + "join sim_events e on e.run_id=i.run_id and e.payload->>'incident_id'=i.id::text "
        "where o.run_id=%s and o.status='failed' and e.event_type in ('sla.breached','sla.report_missing','sla.first_response_overdue') "
        "and not exists(select 1 from behavior_evidence x where x.run_id=o.run_id and x.client_id=o.client_id and x.source_kind='sla' and x.source_id=e.id) order by e.sim_time,e.id,o.client_id",
        (run_id,),
    )
    for client, event, at in await rows.fetchall():
        await store._enqueue(run_id, client, "sla", event, at)
    rows = await conn.execute(
        "select distinct o.client_id,i.id,coalesce(i.resolved_sim,i.closed_sim) at"
        + cause
        + "where o.run_id=%s and o.status='failed' and i.status in ('resolved','closed') and coalesce(i.resolved_sim,i.closed_sim) is not null "
        "and not exists(select 1 from behavior_evidence x where x.run_id=o.run_id and x.client_id=o.client_id and x.source_kind='resolution' and x.source_id=i.id) order by at,i.id,o.client_id",
        (run_id,),
    )
    for client, incident, at in await rows.fetchall():
        await store._enqueue(run_id, client, "resolution", incident, at)
