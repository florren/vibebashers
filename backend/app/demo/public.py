"""Самостоятельный публичный показ: один запуск и цикл исходов на новые инциденты."""

from __future__ import annotations

import datetime as dt
from typing import Any

from psycopg.rows import tuple_row

from app.demo.settings import configuration, save
from app.sim.events import dumps

OUTCOMES = ("on_time", "late", "no_work", "failed")


async def public_context(conn: Any) -> tuple[int, dt.datetime]:
    # Общая блокировка создания переживает конкурирующие сессии и рестарт процесса.
    await conn.execute("select pg_advisory_xact_lock(269,3)")
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(
            "select id,started_sim from sim_runs where settings_snapshot->>'created_by'='public_demo' and status='paused' order by id desc limit 1"
        )
        row = await cur.fetchone()
        if row:
            return int(row[0]), row[1]
        await cur.execute("select seed,sim_time from sim_state where id=1")
        state = await cur.fetchone()
        if state is None:
            raise RuntimeError("нет состояния симуляции")
        await cur.execute(
            "insert into sim_runs(kind,label,seed,reset_mode,status,started_sim,settings_snapshot) values ('live','Публичная демонстрация агента',%s,'none','paused',%s,%s::jsonb) returning id",
            (state[0], state[1], dumps({"created_by": "public_demo"})),
        )
        row = await cur.fetchone()
    assert row is not None
    rid = int(row[0])
    await save(
        conn,
        rid,
        {
            "public_demo": True,
            "base_time": state[1].isoformat(),
            "mode": "simulation",
            "auto_advance": True,
            "emulate_humans": True,
            "enabled": True,
            "status": "paused",
            "team_outcome": OUTCOMES[0],
        },
    )
    return rid, state[1]


async def assign_outcomes(conn: Any, rid: int, ids: list[int]) -> dict[int, str]:
    # Выделяем исход транзакционно до первого отложенного действия команды.
    await conn.execute("select id from sim_runs where id=%s for update", (rid,))
    config = await configuration(conn, rid)
    assigned = dict(config.get("incident_outcomes") or {})
    cursor = int(config.get("outcome_cursor") or 0)
    for iid in sorted(ids):
        if str(iid) not in assigned:
            assigned[str(iid)] = OUTCOMES[cursor % len(OUTCOMES)]
            cursor += 1
    config.update(incident_outcomes=assigned, outcome_cursor=cursor)
    await save(conn, rid, config)
    return {iid: assigned[str(iid)] for iid in ids}


async def recover_public_cases(app: Any, conn: Any, rid: int, *, now: dt.datetime | None = None) -> None:
    """Второй сценарий: повтор ускоряет восстановление, иначе оно начинается через 30 секунд."""
    from app.demo.execution import execution_lock
    from app.demo.recovery import recover_incident

    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(seconds=30)
    async with execution_lock(app, public_demo=True):
        rows = await (
            await conn.execute(
                "select i.id from incidents i where i.run_id=%s and i.status='escalated' "
                "and (select ta.payload->>'outcome' from team_actions ta where ta.incident_id=i.id order by ta.action_sim desc,ta.id desc limit 1) in ('failed','no_work') "
                "and exists(select 1 from notifications n where n.incident_id=i.id and n.template_code='demo_unresolved') "
                "and not exists(select 1 from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=i.id and (s.status in ('new','processing','awaiting_human') or exists(select 1 from agent_runs a where a.signal_id=s.id and a.kind='agent' and (a.outcome is null or a.outcome='awaiting_human')))) "
                "and ((select min(n.created_at) from notifications n where n.incident_id=i.id and n.template_code='demo_unresolved')<=%s "
                "or exists(select 1 from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=i.id and s.channel_subtype='ui_pers_demo' and s.received_at>(select min(n.created_at) from notifications n where n.incident_id=i.id and n.template_code='demo_unresolved'))) order by i.id",
                (rid, cutoff),
            )
        ).fetchall()
        for (iid,) in rows:
            await recover_incident(app, conn, int(iid), public_demo=True)
