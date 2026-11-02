"""Durable adapter прежних World timers; без новых probability/текстовых policy."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, fields
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.sim.behavior.store import BehaviorStore

if TYPE_CHECKING:
    from app.sim.generators import PendingSignal


async def persist(conn: psycopg.AsyncConnection[Any], run_id: int, pending: list[PendingSignal]) -> None:
    BehaviorStore(conn).require_transaction()
    for item in pending:
        await conn.execute(
            "insert into behavior_pending_signals(run_id,client_id,due_sim,client_snapshot,signal_type,product_code,source_operation_id,source_fault_id,error_code,system_code,correlation_id) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                run_id,
                item.client.id,
                item.due_sim,
                Jsonb(asdict(item.client)),
                item.signal_type,
                item.product,
                item.source_operation_id,
                item.source_fault_id,
                item.error_code,
                item.system,
                item.correlation_id,
            ),
        )


async def due(conn: psycopg.AsyncConnection[Any], run_id: int, at: dt.datetime) -> list[tuple[int, PendingSignal]]:
    from app.sim.generators import ClientRow, PendingSignal

    BehaviorStore(conn).require_transaction()
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select * from behavior_pending_signals where run_id=%s and consumed_sim is null and due_sim<=%s order by due_sim,id for update",
            (run_id, at),
        )
        rows = await cur.fetchall()
    result = []
    for row in rows:
        snapshot = row["client_snapshot"]
        if not isinstance(snapshot, dict) or set(snapshot) != {item.name for item in fields(ClientRow)}:
            raise ValueError("legacy World timer требует полный ClientRow snapshot без defaults")
        if (
            isinstance(snapshot["id"], bool)
            or not isinstance(snapshot["id"], int)
            or snapshot["id"] != row["client_id"]
        ):
            raise ValueError("World timer client snapshot не совпадает с FK")
        if any(
            not isinstance(snapshot[key], str) or not snapshot[key]
            for key in ("segment", "psychotype", "region_code", "city", "card_last4")
        ):
            raise ValueError("World timer требует строковые client attributes")
        if not isinstance(snapshot["products"], list) or any(
            not isinstance(item, str) for item in snapshot["products"]
        ):
            raise ValueError("World timer products должны быть списком кодов")
        probability = snapshot["p_complain"]
        weights = snapshot["channel_weights"]
        delay = snapshot["complain_delay_min"]
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(probability)
            or not 0 <= probability <= 1
        ):
            raise ValueError("World timer p_complain вне domain")
        if (
            not isinstance(weights, dict)
            or not weights
            or any(
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                for key, value in weights.items()
            )
            or sum(weights.values()) <= 0
        ):
            raise ValueError("World timer channel weights некорректны")
        if (
            not isinstance(delay, list)
            or len(delay) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in delay)
            or delay[0] > delay[1]
        ):
            raise ValueError("World timer delay должен иметь явные целые границы")
        # Снимок создан самим World через asdict; неизвестные/неполные shapes не
        # восстанавливаются из текущего изменившегося справочника клиента.
        result.append(
            (
                row["id"],
                PendingSignal(
                    row["due_sim"],
                    ClientRow(**snapshot),
                    row["signal_type"],
                    row["product_code"],
                    row["source_operation_id"],
                    row["source_fault_id"],
                    row["error_code"],
                    row["system_code"],
                    row["correlation_id"],
                ),
            )
        )
    return result


async def consumed(conn: psycopg.AsyncConnection[Any], timer_id: int, at: dt.datetime) -> None:
    await conn.execute(
        "update behavior_pending_signals set consumed_sim=%s where id=%s and consumed_sim is null", (at, timer_id)
    )
