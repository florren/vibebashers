"""Native журнал планировщика: enrollment и план атомарны с caller tick TX/RNG."""

from __future__ import annotations

import datetime as dt
from typing import Any, NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import tuple_row

from app.contracts.registry import validate
from app.sim.events import EventBus


class TeamPlanError(ValueError):
    """Неизвестный старый план нельзя восстановить повторным случайным выбором."""


def reject(run_id: int, incident_id: int | None, code: str) -> NoReturn:
    raise TeamPlanError(
        f"run_id={run_id}, incident_id={incident_id}: {code}. "
        "План команды не подтверждён; данные сохранены. Создайте новый run или оставьте прежний остановленным до review."
    )


async def _all(conn: psycopg.AsyncConnection[Any], query: str, values: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(query, values)
        return await cur.fetchall()


async def _one(conn: psycopg.AsyncConnection[Any], query: str, values: tuple[Any, ...]) -> tuple[Any, ...] | None:
    rows = await _all(conn, query, values)
    return rows[0] if rows else None


async def ensure_runtime(conn: psycopg.AsyncConnection[Any], run_id: int, at: dt.datetime) -> None:
    """Один enrollment в caller TX; неизвестные legacy active планы не реконструируются."""
    if conn.autocommit and conn.info.transaction_status != TransactionStatus.INTRANS:
        raise TeamPlanError("Планировщику необходима общая транзакция с RNG")

    async def has_marker() -> bool:
        rows = await _all(
            conn,
            "select payload from sim_events where run_id=%s and event_type='team.runtime_started' order by id",
            (run_id,),
        )
        if rows and (len(rows) != 1 or validate(rows[0][0], "sim/team_runtime")):
            reject(run_id, None, "team_runtime_marker_invalid")
        return bool(rows)

    if await has_marker():
        return
    # Блокировка нужна лишь первому enrollment, обычный tick её не удерживает.
    await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"team-runtime:{run_id}",))
    if await has_marker():
        return
    missing = await _one(
        conn,
        "select i.id from incidents i where i.run_id=%s "
        "and i.status not in ('closed','resolved','duplicate','rejected') and not exists ("
        "select 1 from team_actions a where a.run_id=i.run_id and a.incident_id=i.id "
        "and jsonb_typeof(a.payload->'plan')='object') order by i.id limit 1",
        (run_id,),
    )
    if missing:
        reject(run_id, int(missing[0]), "legacy_team_plan_unknown")
    lost = await _one(
        conn,
        "select incident_id from team_actions where run_id=%s and action='release' "
        "and jsonb_typeof(payload->'plan') is distinct from 'object' order by id limit 1",
        (run_id,),
    )
    if lost:
        reject(run_id, int(lost[0]), "legacy_team_pending_unknown")
    await EventBus(conn).emit(run_id, "team.runtime_started", {"version": 1}, at)


async def native_plans(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[int, dict[str, Any]]:
    """Проверка native run/incident/team/version; загрузка без случайных выборов."""
    rows = await _all(
        conn,
        "select e.payload,i.id from sim_events e left join incidents i "
        "on i.run_id=e.run_id and e.payload->'incident_id'=to_jsonb(i.id) "
        "where e.run_id=%s and e.event_type='team.plan' order by e.id",
        (run_id,),
    )
    result: dict[int, dict[str, Any]] = {}
    for payload, iid in rows:
        if validate(payload, "sim/team_plan") or iid is None:
            reject(run_id, iid, "team_plan_invalid_lineage")
        if iid in result or payload["team"] != payload["plan"]["team_code"]:
            reject(run_id, iid, "team_plan_ambiguous")
        _validate_times(payload["plan"], run_id, iid)
        result[int(iid)] = payload["plan"]
    return result


def _validate_times(blob: dict[str, Any], run_id: int, iid: int) -> None:
    for step in blob["steps"]:
        for value in (step["at"], step["due"]):
            if value is not None:
                try:
                    parsed = dt.datetime.fromisoformat(value)
                except ValueError:
                    reject(run_id, iid, "team_plan_time_invalid")
                if parsed.utcoffset() is None:
                    reject(run_id, iid, "team_plan_time_naive")


def legacy_blob(blob: Any, run_id: int, iid: int) -> dict[str, Any]:
    """Старые action snapshots остаются фактами, неизвестная структура не приводится молча."""
    if not isinstance(blob, dict):
        reject(run_id, iid, "legacy_team_plan_invalid")
    normalized = {"outcome": None, "paused_after_clarify": False, "resumed": False, **blob}
    payload = {
        "event_type": "team.plan",
        "version": 1,
        "incident_id": iid,
        "team": blob.get("team_code"),
        "plan": normalized,
    }
    if validate(payload, "sim/team_plan"):
        reject(run_id, iid, "legacy_team_plan_invalid")
    _validate_times(normalized, run_id, iid)
    return normalized
