"""Запуски эмуляции (ТЗ 4.6–4.7): текущий запуск, free/live, stop, карточка SimRun с v_run_counters."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from app.sim.events import dumps
from app.sim.run_summary import build_summary

RUN_COLS = "id, kind, label, scenario_id, seed, llm_profile_id, reset_mode, parent_run_id, status, started_sim, finished_sim, started_at, finished_at, resumed_count, summary"


def _row_to_run(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = [c.strip() for c in RUN_COLS.split(",")]
    return dict(zip(keys, row, strict=True))


async def get_run(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[str, Any] | None:
    cur = await conn.execute(f"select {RUN_COLS} from sim_runs where id = %s", (run_id,))  # noqa: S608
    row = await cur.fetchone()
    if not row:
        return None
    run = _row_to_run(row)
    cnt = await conn.execute("select to_jsonb(v) from v_run_counters v where v.run_id = %s", (run_id,))
    c = await cnt.fetchone()
    run["counters"] = {
        k: v
        for k, v in (c[0] if c else {}).items()
        if k not in ("run_id", "kind", "label", "status", "started_sim", "finished_sim")
    }
    return run


async def list_runs(conn: psycopg.AsyncConnection[Any], limit: int = 50) -> list[dict[str, Any]]:
    cur = await conn.execute(f"select {RUN_COLS} from sim_runs order by id desc limit %s", (limit,))  # noqa: S608
    return [_row_to_run(r) for r in await cur.fetchall()]


async def current_run_id(conn: psycopg.AsyncConnection[Any]) -> int | None:
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute("select current_run_id from sim_state where id = 1")
        row = await cur.fetchone()
    return int(row[0]) if row and row[0] else None


async def create_run(
    conn: psycopg.AsyncConnection[Any],
    *,
    kind: str,
    label: str,
    seed: int,
    sim_time: dt.datetime,
    reset_mode: str = "counters",
    parent_run_id: int | None = None,
    scenario_id: str | None = None,
) -> int:
    """Новый запуск; незавершённый текущий переводится в stopped (reset_mode=counters)."""
    cur_id = await current_run_id(conn)
    if cur_id:
        async with conn.cursor(row_factory=tuple_row) as previous:
            await previous.execute("select status from sim_runs where id=%s", (cur_id,))
            previous_row = await previous.fetchone()
        if previous_row and previous_row[0] in ("running", "paused", "interrupted"):
            await set_run_status(conn, cur_id, "stopped", sim_time)
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(
            "insert into sim_runs (kind, label, scenario_id, seed, reset_mode, parent_run_id, status, started_sim, settings_snapshot) values (%s, %s, %s, %s, %s, %s, 'running', %s, %s::jsonb) returning id",
            (
                kind,
                label,
                scenario_id,
                seed,
                reset_mode,
                parent_run_id or cur_id,
                sim_time,
                dumps({"created_by": "sim_control"}),
            ),
        )
        run_id = int((await cur.fetchone())[0])  # type: ignore[index]
    await conn.execute("update sim_state set current_run_id = %s, updated_at = now() where id = 1", (run_id,))
    await conn.execute(
        "select pg_notify('runs', %s)",
        (dumps({"type": "started", "run_id": run_id, "data": {"id": run_id, "kind": kind, "label": label}}),),
    )
    return run_id


async def ensure_live_run(conn: psycopg.AsyncConnection[Any]) -> int:
    """Текущий запуск либо один kind=live, если указатель пуст (ТЗ 4.7).

    Строка sim_state блокируется в этой транзакции. Часы не включаются: sim_state.running не меняется,
    started_sim берётся из sim_state.sim_time. create_run вызывается только при current_run_id IS NULL,
    поэтому уже текущие baseline/free/scenario не останавливаются.
    """
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute("select current_run_id, seed, sim_time from sim_state where id = 1 for update")
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError("нет строки sim_state id=1")
    current_id, seed, sim_time = row
    if current_id is not None:
        return int(current_id)
    return await create_run(
        conn,
        kind="live",
        label="живой показ",
        seed=int(seed),
        sim_time=sim_time,
        reset_mode="none",
    )


async def set_run_status(
    conn: psycopg.AsyncConnection[Any], run_id: int, status: str, sim_time: dt.datetime | None = None
) -> None:
    if status in ("stopped", "completed"):
        async with conn.transaction():
            await conn.execute(
                "update sim_runs set status=%s,finished_sim=coalesce(%s,finished_sim,(select sim_time from sim_state where id=1),started_sim),finished_at=coalesce(finished_at,now()) where id=%s",
                (status, sim_time, run_id),
            )
            summary = await build_summary(conn, run_id, refresh_economics=True)
            await conn.execute("update sim_runs set summary=%s::jsonb where id=%s", (dumps(summary), run_id))
    else:
        await conn.execute(
            "update sim_runs set status = %s, resumed_count = resumed_count + %s, "
            "finished_at=case when %s='running' then null else finished_at end, "
            "finished_sim=case when %s='running' then null else finished_sim end, "
            "summary=case when %s='running' then null else summary end where id = %s",
            (status, 1 if status == "running" else 0, status, status, status, run_id),
        )
    await conn.execute(
        "select pg_notify('runs', %s)",
        (dumps({"type": status, "run_id": run_id, "data": {"id": run_id, "status": status}}),),
    )
