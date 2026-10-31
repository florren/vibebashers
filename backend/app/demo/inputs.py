"""Подключение ручных входов к управляемому контуру команд и сотрудников."""

from typing import Any

from psycopg.rows import tuple_row

from app.demo.settings import ensure, save
from app.sim import runs


async def prepare(request: Any, conn: Any, run_id: int) -> int:
    sim = getattr(request.app.state, "sim", None)
    if sim is None:
        return run_id
    sim.full_execution = True
    async with sim._lock:
        async with conn.cursor(row_factory=tuple_row) as current:
            await current.execute("select current_run_id from sim_state where id=1")
            pointer = await current.fetchone()
        if pointer and pointer[0]:
            run_id = int(pointer[0])
        async with conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute("select kind,status from sim_runs where id=%s", (run_id,))
            row = await cur.fetchone()
        if row and (row[0] == "baseline" or row[1] in ("completed", "stopped", "archived")):
            run_id = await runs.create_run(
                conn,
                kind="live",
                label="Живые обращения: команды и сотрудники",
                seed=sim.seed,
                sim_time=sim.clock.sim_time,
                reset_mode="none",
            )
            sim.run_id, sim.run_status, sim.world = run_id, "running", None
        config = await ensure(conn, run_id, running=sim.clock.running)
        if config.get("status") == "finished":
            config.update(enabled=True, status="running" if sim.clock.running else "paused")
            await save(conn, run_id, config)
    return run_id
