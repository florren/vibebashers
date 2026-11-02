"""T-039: служебный вход только по фактическим same-run fault/operation facts.

Не создаёт инциденты, уведомления или клиентские состояния: они принадлежат
обычному графу/инструментам и behavior owner. Все вызовы используют внешнюю TX.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.ingest.normalizer import create_signal

SOURCE = "fault_monitor"


def is_service(signal: dict[str, Any]) -> bool:
    return signal.get("origin") == "proactive" and signal.get("channel_subtype") == "system_logs"


async def rows(conn: psycopg.AsyncConnection[Any], sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(sql, args)
        return list(await cursor.fetchall())


async def current_clock(
    conn: psycopg.AsyncConnection[Any], run_id: int | None = None
) -> tuple[int, dt.datetime] | None:
    """Payload/received_sim не определяют время или владельца автоматических effects."""
    found = await rows(
        conn,
        "select r.id,st.sim_time from sim_state st join sim_runs r on r.id=st.current_run_id "
        "where st.id=1 and r.kind in ('free','scenario') and r.status in ('running','paused') "
        "and (%s::bigint is null or r.id=%s)",
        (run_id, run_id),
    )
    return (int(found[0]["id"]), found[0]["sim_time"]) if found else None


async def fault_scope(
    conn: psycopg.AsyncConnection[Any], run_id: int, fault_id: int, at: dt.datetime
) -> dict[str, Any] | None:
    """Полный impact на момент at; sample/event counters и baseline не являются фактами."""
    found = await rows(
        conn,
        "select f.id,f.system_code,f.error_code,f.started_sim,e.title_ru,e.product_code,"
        "e.default_complexity,e.default_criticality from faults f join error_codes e on e.code=f.error_code "
        "where f.id=%s and f.run_id=%s and f.started_sim<=%s "
        "and (f.resolved_sim is null or f.resolved_sim>%s) and e.system_code=f.system_code "
        "and exists(select 1 from sim_events v where v.run_id=f.run_id and v.event_type='fault.started' "
        "and v.payload->>'fault_id'=f.id::text and v.sim_time<=%s)",
        (fault_id, run_id, at, at, at),
    )
    if not found:
        return None
    clients = await rows(
        conn,
        "select distinct on(o.client_id) o.client_id,o.id operation_id,o.product_code,o.started_sim,"
        "c.display_name,c.segment_code,c.consents,c.contacts,p.name_ru product_name,"
        "count(*) over(partition by o.client_id) operation_count "
        "from operations o join clients c on c.id=o.client_id join products p on p.code=o.product_code "
        "where o.run_id=%s and o.fault_id=%s and o.started_sim<=%s "
        "and behavior_valid_failed_operation(o.id,%s) order by o.client_id,o.started_sim,o.id",
        (run_id, fault_id, at, run_id),
    )
    products = {client["product_code"] for client in clients}
    return {
        **found[0],
        "product_code": found[0]["product_code"] or (next(iter(products)) if len(products) == 1 else None),
        "as_of": at,
        "clients": clients,
        "affected_count": len(clients),
        "operation_count": sum(client["operation_count"] for client in clients),
    }


def summary(scope: dict[str, Any]) -> dict[str, Any]:
    """Compact tool/checkpoint evidence; полный recipient set повторно читается перед effects."""
    return {key: value for key, value in scope.items() if key != "clients"}


def preferred_channel(person: dict[str, Any]) -> str | None:
    """Существующие consent и preferred; другого канала при отказе не подбираем."""
    if (person.get("consents") or {}).get("proactive") is not True:
        return None
    channel = (person.get("contacts") or {}).get("preferred")
    return channel if channel in ("chat", "call", "email", "telegram_bot") else None


async def pending_delivery(
    conn: psycopg.AsyncConnection[Any], signal_id: int, run_id: int, scope: dict[str, Any]
) -> bool:
    existing = await rows(
        conn,
        "select client_id from notifications where run_id=%s and signal_id=%s "
        "and template_code='proactive_fault' and recipient_type='client'",
        (run_id, signal_id),
    )
    known = {row["client_id"] for row in existing}
    return any(person["client_id"] not in known and preferred_channel(person) for person in scope["clients"])


async def service_scope(
    conn: psycopg.AsyncConnection[Any], signal: dict[str, Any], run_id: int
) -> dict[str, Any] | None:
    """Origin сам по себе не даёт operational authority; проверяем producer lineage."""
    fault_id = signal.get("source_fault_id")
    if (
        not is_service(signal)
        or signal.get("channel") != "proactive"
        or signal.get("client_id") is not None
        or not isinstance(fault_id, int)
        or isinstance(fault_id, bool)
        or fault_id <= 0
    ):
        return None
    provenance = await rows(
        conn,
        "select m.id from ingest_messages m join signals s on s.id=m.signal_id "
        "where s.id=%s and s.run_id=%s and m.run_id=s.run_id and m.source_code=%s "
        "and m.status='accepted' and m.external_id=%s "
        "and m.payload->>'origin'='proactive' and m.payload->>'channel'='proactive' "
        "and m.payload#>>'{meta,source_fault_id}'=s.source_fault_id::text "
        "and m.payload#>>'{client,client_id}' is null",
        (signal["id"], run_id, SOURCE, f"fault-{run_id}-{fault_id}"),
    )
    clock = await current_clock(conn, run_id) if provenance else None
    return await fault_scope(conn, run_id, fault_id, clock[1]) if clock else None


async def causal_fault(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    client_id: int,
    operation_id: int | None,
    fault_id: int | None,
    at: dt.datetime,
) -> int | None:
    """Источник клиента обязан иметь реальную same-run/client failed operation."""
    found = await rows(
        conn,
        "select o.fault_id from operations o where o.run_id=%s and o.client_id=%s "
        "and o.fault_id is not null and o.started_sim<=%s and behavior_valid_failed_operation(o.id,%s) "
        "and ((%s::bigint is not null and o.id=%s) or (%s::bigint is null and o.fault_id=%s)) "
        "order by o.started_sim,o.id limit 1",
        (run_id, client_id, at, run_id, operation_id, operation_id, operation_id, fault_id),
    )
    return int(found[0]["fault_id"]) if found else None


async def produce(conn: psycopg.AsyncConnection[Any]) -> list[int]:
    """Повторяемый wakeup: impact0 ждёт actual operations, потеря NOTIFY не теряет работу."""
    clock = await current_clock(conn)
    if clock is None:
        return []
    run_id, at = clock
    faults = await rows(
        conn,
        "select id from faults where run_id=%s and started_sim<=%s "
        "and (resolved_sim is null or resolved_sim>%s) order by id",
        (run_id, at, at),
    )
    signal_ids: list[int] = []
    for fault in faults:
        fault_id = int(fault["id"])
        await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"proactive:{run_id}:{fault_id}",))
        scope = await fault_scope(conn, run_id, fault_id, at)
        if not scope or not scope["affected_count"]:
            continue
        result = await create_signal(
            conn,
            {
                "channel": "proactive",
                "channel_subtype": "system_logs",
                "origin": "proactive",
                "external_id": f"fault-{run_id}-{fault_id}",
                "client": {"client_id": None},
                "text": (
                    f"Служебный мониторинг: {scope['title_ru']}. Ошибка {scope['error_code']}; "
                    f"система {scope['system_code']}. Подтверждены неуспешные операции "
                    f"{scope['affected_count']} клиентов. Требуется проактивное уведомление и устранение сбоя."
                ),
                "timestamp": at.isoformat(),
                "geo": {"source": "none"},
                "meta": {"source_fault_id": fault_id},
            },
            source_code=SOURCE,
            run_id=run_id,
            sim_time=at,
            _internal_producer="fault_monitor",
        )
        if result["status"] not in ("accepted", "duplicate") or result.get("signal_id") is None:
            raise ValueError("служебный сигнал сбоя не принят normalizer")
        signal_ids.append(int(result["signal_id"]))
    return signal_ids
