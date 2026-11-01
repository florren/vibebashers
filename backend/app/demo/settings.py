"""Сохранённый профиль совместной работы команд и сотрудников; без запуска LLM."""

from typing import Any

from psycopg.rows import tuple_row

from app.sim.events import dumps


async def configuration(conn: Any, run_id: int) -> dict[str, Any]:
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(
            "select settings_snapshot->'demo_execution' from sim_runs where id=%s and kind<>'baseline'", (run_id,)
        )
        row = await cur.fetchone()
    return dict(row[0] or {}) if row else {}


async def save(conn: Any, run_id: int, value: dict[str, Any]) -> None:
    await conn.execute(
        "update sim_runs set settings_snapshot=jsonb_set(settings_snapshot,'{demo_execution}',%s::jsonb) where id=%s and kind<>'baseline'",
        (dumps(value), run_id),
    )


async def ensure(conn: Any, run_id: int, *, running: bool) -> dict[str, Any]:
    current = await configuration(conn, run_id)
    if current:
        return current
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute("select kind from sim_runs where id=%s", (run_id,))
        row = await cur.fetchone()
        if not row or row[0] == "baseline":
            return {}
        await cur.execute("select value from settings where key='simulation_execution'")
        defaults = await cur.fetchone()
    values = dict(defaults[0] or {}) if defaults else {}
    current = {
        "mode": "simulation",
        "scenario_id": None,
        "team_outcome": values.get("team_outcome", "on_time"),
        "emulate_humans": values.get("emulate_humans", True),
        "auto_advance": values.get("auto_advance", True),
        "enabled": True,
        "status": "running" if running else "paused",
        "error": None,
    }
    await save(conn, run_id, current)
    return current
