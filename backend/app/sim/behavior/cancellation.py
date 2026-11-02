"""Атомарные receipts отмены: native связи и полнота, без attribution Sent/RNG."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.sim.behavior.cancellation_details import CancellationDetails
from app.sim.behavior.facts import related, rows
from app.sim.behavior.signals import canonical, classified, is_complaint
from app.sim.behavior.store import BehaviorStore


async def complaint_observation(
    conn: psycopg.AsyncConnection[Any], current: dict[str, Any], at: dt.datetime
) -> tuple[dt.datetime | None, bool]:
    """Неизвестный classifier связанного входа не превращается в neutral/ноль."""
    first = current["first_complaint_sim"]
    # Snapshot относится к запрошенному cutoff; поздний факт остаётся в runtime.
    if first is not None and first > at:
        first = None
    complete = True
    signals = await rows(
        conn,
        "select id,received_sim from signals where run_id=%s and client_id=%s and origin<>'proactive' "
        "and received_sim>=%s and received_sim<=%s order by received_sim,id",
        (current["run_id"], current["client_id"], current["opened_sim"], at),
    )
    for signal in signals:
        if not await related(conn, current, signal_id=signal["id"], incident_id=None):
            continue
        observation = await classified(conn, current["run_id"], current["client_id"], signal["id"])
        if observation is None:
            complete = False
        elif is_complaint(observation["classification"]):
            first = min(first, signal["received_sim"]) if first is not None else signal["received_sim"]
    return first, complete


async def resolution_time(
    conn: psycopg.AsyncConnection[Any], current: dict[str, Any], at: dt.datetime, incident: int
) -> dt.datetime | None:
    """Последнее обязательное native решение, не logical/observation tick."""
    run, client, episode = current["run_id"], current["client_id"], current["episode_no"]
    evidence = await rows(
        conn,
        "select coalesce(resolved_sim,closed_sim) at from incidents where id=%s and run_id=%s "
        "and status in ('resolved','closed') and coalesce(resolved_sim,closed_sim)<=%s",
        (incident, run, at),
    )
    if not evidence or not await related(conn, current, signal_id=None, incident_id=incident):
        return None
    stamps = [evidence[0]["at"]]
    causes = await rows(
        conn,
        "select b.operation_id,b.fault_id,f.resolved_sim from behavior_causes b "
        "left join faults f on f.id=b.fault_id and f.run_id=b.run_id "
        "where b.run_id=%s and b.client_id=%s and b.episode_no=%s order by b.operation_id",
        (run, client, episode),
    )
    signal_causes = await rows(
        conn,
        "select source_id from behavior_receipts where run_id=%s and client_id=%s "
        "and source_kind='signal' and action=%s order by source_id",
        (run, client, f"cause:{episode}"),
    )
    if not causes and not signal_causes:
        return None
    for cause in causes:
        if cause["fault_id"] is not None:
            if cause["resolved_sim"] is None or cause["resolved_sim"] > at:
                return None
            stamps.append(cause["resolved_sim"])
        solved = await rows(
            conn,
            "select min(coalesce(i.resolved_sim,i.closed_sim)) at from incidents i "
            "where i.run_id=%s and i.status in ('resolved','closed') and coalesce(i.resolved_sim,i.closed_sim)<=%s "
            "and ((%s::bigint is not null and i.fault_id=%s) or exists("
            "select 1 from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=i.id "
            "and s.run_id=i.run_id and s.client_id=%s and (s.source_operation_id=%s "
            "or (%s::bigint is not null and s.source_fault_id=%s))))",
            (
                run,
                at,
                cause["fault_id"],
                cause["fault_id"],
                client,
                cause["operation_id"],
                cause["fault_id"],
                cause["fault_id"],
            ),
        )
        if solved[0]["at"] is None:
            return None
        stamps.append(solved[0]["at"])
    for cause in signal_causes:
        solved = await rows(
            conn,
            "with recursive lineage as (select id,parent_signal_id,array[id] path,1 depth from signals "
            "where id=%s and run_id=%s and client_id=%s union all "
            "select p.id,p.parent_signal_id,l.path||p.id,l.depth+1 from lineage l join signals p on p.id=l.parent_signal_id "
            "where p.run_id=%s and p.client_id=%s and l.depth<64 and not p.id=any(l.path)) "
            "select min(coalesce(i.resolved_sim,i.closed_sim)) at from lineage l "
            "join incident_signals x on x.signal_id=l.id join incidents i on i.id=x.incident_id "
            "where i.run_id=%s and i.status in ('resolved','closed') and coalesce(i.resolved_sim,i.closed_sim)<=%s",
            (cause["source_id"], run, client, run, client, run, at),
        )
        if solved[0]["at"] is None:
            return None
        stamps.append(solved[0]["at"])
    result = max(stamps)
    if not isinstance(result, dt.datetime) or result.utcoffset() is None:
        raise ValueError("native resolution timestamp повреждён")
    return result


async def cancel_pending(
    conn: psycopg.AsyncConnection[Any],
    current: dict[str, Any],
    evidence: dict[str, Any],
    *,
    at: dt.datetime,
    observed_at: dt.datetime,
    canonical_signal_id: int | None = None,
) -> None:
    """Receipt/status в caller TX; pending work блокируется до обеих записей."""
    BehaviorStore(conn).require_transaction()
    run, client, episode = current["run_id"], current["client_id"], current["episode_no"]
    native = await rows(
        conn,
        "select * from behavior_evidence where id=%s and run_id=%s and client_id=%s "
        "and source_kind=%s and source_id=%s",
        (evidence["id"], run, client, evidence["source_kind"], evidence["source_id"]),
    )
    if len(native) != 1 or evidence["source_kind"] not in ("resolution", "agent_state"):
        raise ValueError("cancellation требует native same-run/client evidence")
    first, complete = await complaint_observation(conn, current, at)
    resolution = None
    if evidence["source_kind"] == "agent_state":
        signal = await canonical(conn, run, client, canonical_signal_id) if canonical_signal_id is not None else None
        intent = await rows(
            conn,
            "select signal_id from behavior_agent_intents where id=%s and run_id=%s and client_id=%s",
            (evidence["source_id"], run, client),
        )
        if signal is None or not intent or intent[0]["signal_id"] != canonical_signal_id:
            raise ValueError("already_complained требует фактическую canonical complaint/intent")
        first = min(first, signal["received_sim"]) if first is not None else signal["received_sim"]
    else:
        resolution = await resolution_time(conn, current, at, evidence["source_id"])
    work = await rows(
        conn,
        "select * from behavior_work where run_id=%s and client_id=%s and episode_no=%s and status='pending' "
        "and (%s='resolution' or kind='complaint') order by id for update",
        (run, client, episode, evidence["source_kind"]),
    )
    for timer in work:
        details = CancellationDetails(
            episode,
            timer["kind"],
            timer["due_sim"],
            at,
            observed_at,
            first,
            complete,
            evidence["id"],
            evidence["source_kind"],
            evidence["source_id"],
            canonical_signal_id,
            resolution,
        )
        inserted = await rows(
            conn,
            "insert into behavior_receipts(run_id,client_id,source_kind,source_id,action,consumed_sim,details) "
            "values(%s,%s,'work',%s,%s,%s,%s) on conflict do nothing returning source_id",
            (run, client, timer["id"], details.action, at, Jsonb(details.to_json())),
        )
        if not inserted:
            raise ValueError("pending work уже имеет cancellation receipt: требуется проверка истории")
        await conn.execute("update behavior_work set status='cancelled',consumed_sim=%s where id=%s", (at, timer["id"]))
