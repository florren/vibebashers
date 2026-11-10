"""Контекст только ручного обращения Journey; не владеет часами всего банка."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import HTTPException
from psycopg.rows import tuple_row
from pydantic import BaseModel, ConfigDict, ValidationError

from app.demo.settings import save
from app.sim.events import dumps
from app.sim.team_plans import ensure_runtime


class JourneyOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenario_id: str | None = None
    team_outcome: Literal["on_time", "late", "no_work", "failed", "recovered"] = "on_time"
    emulate_humans: bool = True
    auto_advance: bool = True


async def context(conn: Any, message: dict[str, Any]) -> tuple[int, dt.datetime]:
    """Новый root получает собственный non-current run; дополнение сохраняет его профиль."""
    if message.get("origin") != "jury":
        raise HTTPException(422, "Journey принимает только ручные сигналы origin=jury")
    meta = message.get("meta")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise HTTPException(422, "meta должен быть объектом")
    try:
        options = JourneyOptions.model_validate(meta.get("journey_execution", {}))
    except ValidationError as exc:
        raise HTTPException(422, "Некорректный профиль ручного обращения Journey") from exc
    if options.scenario_id:
        from app.sim.scenarios import get

        if get(options.scenario_id) is None:
            raise HTTPException(422, "Неизвестный сценарий Journey")
    async with conn.cursor(row_factory=tuple_row) as cur:
        # Повтор HTTP не создаёт новый пустой run и не меняет зафиксированный профиль.
        await cur.execute("select pg_advisory_xact_lock(269,4)")
        await cur.execute(
            "select s.run_id,r.started_sim,r.settings_snapshot,s.parent_signal_id from signals s join sim_runs r on r.id=s.run_id "
            "join ingest_messages im on im.signal_id=s.id where im.source_code='journey' and im.external_id=%s",
            (message.get("external_id"),),
        )
        existing = await cur.fetchone()
        parent = meta.get("parent_signal_id")
        if parent is not None and (not isinstance(parent, int) or isinstance(parent, bool) or parent <= 0):
            raise HTTPException(422, "Некорректный parent_signal_id")
        if existing is not None:
            if existing[3] != parent:
                raise HTTPException(422, "Идентификатор запроса уже принадлежит другому сообщению")
            existing = existing[:3]
        if existing is None and parent is not None:
            await cur.execute(
                "select s.run_id,r.started_sim,r.settings_snapshot from signals s join sim_runs r on r.id=s.run_id "
                "where s.id=%s and s.origin='jury' and r.settings_snapshot->>'created_by'='journey_demo'",
                (parent,),
            )
            existing = await cur.fetchone()
            if existing is None:
                raise HTTPException(422, "Дополнение Journey должно принадлежать ручному обращению Journey")
        if existing is not None:
            rid, at, snapshot = existing
            if snapshot.get("created_by") != "journey_demo":
                raise HTTPException(422, "Чужой контекст Journey")
            saved = snapshot.get("demo_execution") or {}
            if "journey_execution" in meta and any(
                saved.get(key) != value for key, value in options.model_dump().items()
            ):
                raise HTTPException(422, "Профиль обращения уже сохранён; создайте новое обращение")
            return int(rid), await clock(conn, int(rid), at)
        if options.team_outcome == "recovered":
            raise HTTPException(
                422, "Восстановление продолжает завершённую неудачную попытку; новое обращение так не запускается"
            )
        await cur.execute("select seed,sim_time from sim_state where id=1")
        state = await cur.fetchone()
        if state is None:
            raise HTTPException(503, "Нет состояния банка")
        await cur.execute(
            "insert into sim_runs(kind,label,seed,reset_mode,status,started_sim,settings_snapshot) "
            "values('live','Ручное обращение Journey',%s,'none','paused',%s,%s::jsonb) returning id",
            (state[0], state[1], dumps({"created_by": "journey_demo"})),
        )
        row = await cur.fetchone()
    assert row is not None
    rid, at = int(row[0]), state[1]
    await conn.execute(
        "insert into ingest_sources(code,kind,channel_code,config,enabled,interval_s,is_external) "
        "values('journey','rest','chat','{}',false,5,false) on conflict(code) do nothing"
    )
    await ensure_runtime(conn, rid, at)
    await save(
        conn,
        rid,
        {
            **options.model_dump(),
            "journey_demo": True,
            "base_time": at.isoformat(),
            "mode": "simulation",
            "enabled": True,
            "status": "paused",
            "error": None,
        },
    )
    return rid, at


async def clock(conn: Any, run_id: int, floor: dt.datetime) -> dt.datetime:
    """Только уже записанные факты своего кейса, без planned due и global SimClock."""
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(
            "select max(at) from (select received_sim at from signals where run_id=%s "
            "union all select sent_sim from notifications where run_id=%s and status in ('sent','delivered') "
            "union all select action_sim from team_actions where run_id=%s) facts",
            (run_id, run_id, run_id),
        )
        row = await cur.fetchone()
    return max(floor, row[0]) if row and row[0] else floor


async def recover(app: Any, conn: Any, run_id: int, config: dict[str, Any]) -> None:
    """Подхватывает потерянный NOTIFY и durable entry своего кейса штатным graph owner."""
    svc = app.state.agent
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(
            "select s.id,a.id from signals s left join lateral "
            "(select id,outcome,interrupted_at,started_at from agent_runs where signal_id=s.id "
            "and kind='agent' order by id desc limit 1) a on true "
            "where s.run_id=%s and ("
            "(a.id is null and s.status='new') or "
            "(a.outcome is null and a.started_at<%s)) order by s.id limit 20",
            (run_id, svc.started_at),
        )
        rows = await cur.fetchall()
    at = await clock(conn, run_id, dt.datetime.fromisoformat(config["base_time"]))
    await conn.commit()  # Recovery использует собственное соединение и shared AgentRun ownership.
    for sid, arid in rows:
        if arid is None:
            svc.submit(int(sid), at, interactive=True)
        else:
            await svc._recover_one(int(arid), at, interactive=True)
