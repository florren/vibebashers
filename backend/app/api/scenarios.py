"""Роутер тега `scenarios` (OpenAPI 1.4.0): список демо-сценариев из data/scenarios и запуск сценария отдельным запуском эмуляции.

Запуск (минимум T-038/T-042): новый sim_run kind=scenario → инъекция сообщений из секции `inject` YAML → агент обрабатывает их
асинхронно (AgentService). Проверка ожиданий — `app.sim.scenarios.evaluate` (тесты L5 и scripts/scenario_check.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api._compliance_support import analyze_in_background
from app.api.common import agent_service, db, fetch_all
from app.db.session import psycopg_dsn
from app.errors import NotImplementedYet
from app.sim import runs as run_svc
from app.sim import scenarios as sc
from app.sim.engine import Simulator

router = APIRouter(tags=["scenarios"])


class ScenarioRunRequest(BaseModel):
    speed_preset: str | None = None
    reset_mode: str = "counters"
    label: str | None = None


@router.get("/api/scenarios", summary="Список демо-сценариев")
async def get_scenarios(request: Request) -> Any:
    async with db() as conn:
        rows = await fetch_all(conn, "select id, last_run_at, last_result from scenarios")
    by_id = {r["id"]: (r["last_run_at"], r["last_result"]) for r in rows}
    return [sc.to_api(s, by_id.get(s["id"])) for s in sc.load_all()]


@router.post(
    "/api/scenarios/{id}/run", summary="Запустить сценарий как отдельный запуск эмуляции (ТЗ 4.6, 18)", status_code=202
)
async def post_scenarios_id_run(request: Request, id: str, body: ScenarioRunRequest | None = None) -> Any:  # noqa: A002
    return await run_scenario(request, id, body)


async def run_scenario(
    request: Request, id: str, body: ScenarioRunRequest | None = None, *, start_paused: bool = False
) -> Any:  # noqa: A002
    scenario = sc.get(id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="сценарий не найден")
    if not sc.is_runnable(scenario):
        raise NotImplementedYet(str(scenario.get("requires") or "B07"))
    body = body or ScenarioRunRequest()
    if body.reset_mode == "baseline":
        raise NotImplementedYet("T-040")
    sim: Simulator = request.app.state.sim
    svc = agent_service(request)
    if start_paused:
        await sim.control("pause")
    await sim.control(
        "start",
        start_paused=start_paused,
        kind="scenario",
        scenario_id=id,
        label=body.label or f"Сценарий {scenario.get('number')}: {scenario.get('title_ru')}",
    )
    if body.speed_preset:
        await sim.control("set_preset", preset=body.speed_preset)
    run_id = sim.run_id
    assert run_id is not None
    injected: list[dict[str, Any]] = []
    transcript: dict[str, Any] | None = None
    async with db() as conn:
        try:
            if sc.is_transcript(scenario):
                transcript = await sc.inject_transcript(conn, scenario, run_id, sim_time=sim.clock.sim_time)
            else:
                injected = await sc.inject(conn, scenario, run_id, sim_time=sim.clock.sim_time)
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await conn.execute("update scenarios set last_run_at = now() where id = %s", (id,))
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as tconn:  # кортежные строки для run_svc
        run = await run_svc.get_run(tconn, run_id)
    for item in injected:
        svc.submit(item["signal_id"], sim.clock.sim_time)
    if transcript:
        asyncio.create_task(analyze_in_background(request, transcript["transcript_id"], pacing_delay_s=1.0))
    client_id = next((i["client_id"] for i in injected if i["client_id"]), None) or (transcript or {}).get("client_id")
    return {"run": run, "client_id": client_id, "transcript_id": (transcript or {}).get("transcript_id")}
