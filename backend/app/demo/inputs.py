"""Подключение ручных входов к управляемому контуру команд и сотрудников."""

from typing import Any

from psycopg.rows import tuple_row

from app.demo.settings import ensure, save
from app.sim import runs


async def prepare(request: Any, conn: Any, run_id: int, *, public_input: bool = False) -> int:
    sim = getattr(request.app.state, "sim", None)
    if sim is None:
        if not public_input:
            return run_id
        # Публичный процесс не содержит Simulator и не получает LLM-ключи.
        async with conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(
                "select st.current_run_id,st.seed,st.sim_time,st.running,r.kind,r.status from sim_state st left join sim_runs r on r.id=st.current_run_id where st.id=1 for update of st"
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("нет состояния симуляции")
        run_id = int(row[0]) if row[0] else run_id
        if row[0] is None or row[4] == "baseline" or row[5] in ("completed", "stopped", "archived"):
            run_id = await runs.create_run(
                conn,
                kind="live",
                label="Живые обращения: команды и сотрудники",
                seed=row[1],
                sim_time=row[2],
                reset_mode="none",
            )
            await runs.set_run_status(conn, run_id, "paused")
        elif row[4] == "live" and row[5] == "running" and not row[3]:
            # run_context мог только что создать live-run при пустом указателе.
            await runs.set_run_status(conn, run_id, "paused")
        config = await ensure(conn, run_id, running=bool(row[3]))
        if config.get("status") == "finished":
            config.update(enabled=True, status="paused", mode="simulation", scenario_id=None)
            await save(conn, run_id, config)
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
            status = "running" if sim.clock.running else "paused"
            if status == "paused":
                await runs.set_run_status(conn, run_id, status)
            sim.run_id, sim.run_status, sim.world = run_id, status, None
        config = await ensure(conn, run_id, running=sim.clock.running)
        if config.get("status") == "finished":
            config.update(
                enabled=True,
                status="running" if sim.clock.running else "paused",
                mode="simulation",
                scenario_id=None,
            )
            await save(conn, run_id, config)
    return run_id
