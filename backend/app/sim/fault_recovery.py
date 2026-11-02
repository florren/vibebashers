"""Восстановление cache сбоев World из native расписания и операций только чтением."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, NoReturn

import psycopg
from psycopg.rows import dict_row

from app.contracts.registry import validate


class FaultScheduleError(ValueError):
    """Неполное расписание не разрешает угадывать срок или correlation_id."""

    def __init__(self, run_public_id: str, fault_id: int, code: str) -> None:
        self.run_public_id = run_public_id
        self.fault_id = fault_id
        self.code = code
        super().__init__(
            f"{run_public_id}, fault_id={fault_id}: {code}. "
            "Расписание сбоя нельзя восстановить; данные сохранены. "
            "Завершите прежний run явно или создайте новый; автоматического исправления нет."
        )


def _reject(row: dict[str, Any], code: str) -> NoReturn:
    # Сообщение содержит только public run reference и публичный fault_id API.
    raise FaultScheduleError(row["run_public_id"], row["id"], code) from None


async def load_faults(conn: psycopg.AsyncConnection[Any], run_id: int) -> list[dict[str, Any]]:
    """Единый MVCC-снимок и часы своего current run, без SQL-записи/commit/RNG."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "with active as ("
            "select f.*,r.public_id run_public_id,st.sim_time as_of from faults f "
            "join sim_runs r on r.id=f.run_id left join sim_state st on st.id=1 and st.current_run_id=f.run_id "
            "where f.run_id=%s and f.resolved_sim is null), "
            "impacted as (select f.id,count(o.id) impact,"
            "coalesce(array_agg(distinct o.client_id order by o.client_id) filter(where o.id is not null),'{}'::bigint[]) clients "
            "from active f left join operations o on o.run_id=f.run_id and o.fault_id=f.id "
            "and o.status='failed' and o.started_sim<=f.as_of and behavior_valid_failed_operation(o.id,f.run_id) "
            "group by f.id) "
            "select f.id,f.system_code,f.error_code,f.started_sim,f.run_public_id,f.as_of,i.impact,i.clients,"
            "e.id event_id,e.event_type,e.payload,e.sim_time event_sim,e.correlation_id "
            "from active f join impacted i on i.id=f.id left join sim_events e on e.run_id=f.run_id "
            "and e.event_type in ('fault.started','fault.regression') and e.payload->'fault_id'=to_jsonb(f.id) "
            "order by f.id,e.id",
            (run_id,),
        )
        rows = await cur.fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["id"], []).append(row)
    result = []
    for fault_id, events in grouped.items():
        row = events[0]

        if row["as_of"] is None:
            _reject(row, "fault_clock_not_current")
        if row["started_sim"] > row["as_of"]:
            _reject(row, "fault_schedule_from_future")
        if len(events) != 1:
            _reject(row, "fault_schedule_ambiguous")
        if row["event_id"] is None:
            _reject(row, "fault_schedule_missing")
        payload = row["payload"]
        schema = "sim/fault" if row["event_type"] == "fault.started" else "sim/fault_regression"
        if not isinstance(payload, dict) or validate(payload, schema):
            _reject(row, "fault_schedule_invalid_event")
        duration = payload.get("expected_duration_min")
        if type(duration) is not int or duration <= 0:
            _reject(row, "fault_schedule_missing_duration")
        try:
            started = dt.datetime.fromisoformat(payload["started_sim"])
            expected_end = started + dt.timedelta(minutes=duration)
        except (ValueError, TypeError, OverflowError):
            _reject(row, "fault_schedule_invalid_time")
        if (
            started.utcoffset() is None
            or started != row["started_sim"]
            or row["event_sim"] != row["started_sim"]
            or payload["event_type"] != row["event_type"]
            or payload["system"] != row["system_code"]
            or payload["error_code"] != row["error_code"]
            or not isinstance(row["correlation_id"], uuid.UUID)
        ):
            _reject(row, "fault_schedule_mismatch")
        result.append(
            {
                "id": fault_id,
                "system": row["system_code"],
                "error_code": row["error_code"],
                "started_sim": row["started_sim"],
                "expected_end": expected_end,
                "impact": row["impact"],
                "clients": set(row["clients"]),
                "corr": row["correlation_id"],
            }
        )
    return result
