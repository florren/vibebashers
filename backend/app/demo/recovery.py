"""Явное продолжение неудачной demo-попытки без замены инцидента и истории."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from app.agent.tools.base import ToolContext
from app.demo.settings import configuration, save
from app.sim.clock import add_working_hours
from app.sim.events import EventBus
from app.sim.rng import SimRng
from app.sim.teams import IncidentPlan, PlannedStep, TeamEmulator


async def recover_incident(app: Any, conn: Any, iid: int, *, public_demo: bool = False) -> None:
    sim, svc = app.state.sim, app.state.agent
    row = await (
        await conn.execute(
            "select i.run_id,i.status,i.team_code,i.title,i.system_code,i.product_code,i.agent_run_id from incidents i where i.id=%s for update",
            (iid,),
        )
    ).fetchone()
    if not row:
        raise HTTPException(404, "Инцидент не найден")
    rid, status, team, title, system, product, arid = row
    config = await configuration(conn, rid)
    if (public_demo and not config.get("public_demo")) or (not public_demo and rid != sim.run_id):
        raise HTTPException(404, "Инцидент не принадлежит текущему запуску")
    last = await (
        await conn.execute(
            "select payload->>'outcome',action_sim from team_actions where incident_id=%s order by action_sim desc,id desc limit 1",
            (iid,),
        )
    ).fetchone()
    if last and last[0] == "recovered":
        return  # Повтор запроса не создаёт новую попытку или уведомление.
    manual = await (
        await conn.execute(
            "select 1 from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=%s and ((%s and s.channel_subtype='ui_pers_demo') or (not %s and s.origin='jury')) limit 1",
            (iid, public_demo, public_demo),
        )
    ).fetchone()
    if status != "escalated" or not last or last[0] not in ("failed", "no_work") or not manual:
        raise HTTPException(409, "Нет завершённой неудачной demo-попытки для восстановления")
    base_time = dt.datetime.fromisoformat(config["base_time"]) if public_demo else sim.clock.sim_time
    at = max(
        base_time,
        last[1],
        dt.datetime.fromisoformat((config.get("manual_times") or {}).get(str(iid), last[1].isoformat())),
    )
    plan = IncidentPlan(
        iid,
        team,
        True,
        False,
        [
            PlannedStep(action, add_working_hours(at, offset))
            for action, offset in (("fix_decision", 0), ("release", 1), ("verify", 2), ("close", 3))
        ],
        outcome="recovered",
    )
    emulator = TeamEmulator(
        SimRng(sim.seed),
        conn,
        EventBus(conn),
        rid,
        demo_outcome="recovered",
        llm=(svc.chain, svc.chain.profile_for("twin", svc.profile)),
        incident_ids=[iid],
    )
    await emulator.load()
    # Новое реальное решение команды сохраняет новый план append-only; старые действия остаются.
    ctx = ToolContext(conn, run_id=rid, agent_run_id=int(arid or 0), sim_time=plan.steps[0].at, llm_source="mock")
    await emulator._execute_step(
        ctx,
        SimpleNamespace(active_faults=[]),
        plan,
        plan.steps[0],
        iid,
        team,
        {"title": title, "system": system, "product": product, "outcome": "recovered"},
        status,
    )
    config["recovery_incidents"] = sorted(set(config.get("recovery_incidents", []) + [iid]))
    config.setdefault("manual_times", {})[str(iid)] = at.isoformat()
    await save(conn, rid, config)
