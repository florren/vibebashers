"""Роутер тега `sim` (OpenAPI 1.4.0). Реализовано (B03/T-031, T-040-минимум): state, control, events, runs (список, current, карточка, stop,
resume). Остальное — 501 до карточек T-040/T-041."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db.session import psycopg_dsn
from app.errors import NotImplementedYet
from app.sim import runs as run_svc
from app.sim.engine import Simulator

router = APIRouter(tags=["sim"])


class SimControlRequest(BaseModel):
    action: Literal["start", "pause", "resume", "stop", "step", "reset_day", "set_speed", "set_preset", "jump_to"]
    label: str | None = None
    speed: float | None = Field(default=None, gt=0)
    preset: Literal["demo_5min", "day_12min", "realtime"] | None = None
    step_minutes: int = Field(default=15, ge=1, le=24 * 60)
    sim_time: dt.datetime | None = None


def _sim(request: Request) -> Simulator:
    sim = getattr(request.app.state, "sim", None)
    if sim is None:
        raise HTTPException(status_code=503, detail="симулятор не запущен (APP_ENV=test?)")
    return sim  # type: ignore[no-any-return]


async def _conn() -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True)


@router.get("/api/sim/state", summary="Текущее состояние симуляции")
async def get_sim_state(request: Request) -> Any:
    return _sim(request).state_dict()


@router.post("/api/sim/control", summary="Старт/Пауза/Возобновить/Стоп/Шаг/Сброс дня/Скорость")
async def post_sim_control(request: Request, body: SimControlRequest) -> Any:
    sim = _sim(request)
    kw = body.model_dump(exclude_none=True)
    action = kw.pop("action")
    if action == "set_speed" and "speed" not in kw:
        raise HTTPException(status_code=422, detail="speed обязателен для set_speed")
    if action == "set_preset" and "preset" not in kw:
        raise HTTPException(status_code=422, detail="preset обязателен для set_preset")
    if action == "jump_to" and "sim_time" not in kw:
        raise HTTPException(status_code=422, detail="sim_time обязателен для jump_to")
    try:
        return await sim.control(action, **kw)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/sim/events", summary="Лента событий симулятора (шина событий)")
async def get_sim_events(
    request: Request,
    run_id: str = Query(default="current"),
    type: str | None = Query(default=None, description="Префикс, напр. fault. или client."),  # noqa: A002
    since_sim: dt.datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> Any:
    async with await _conn() as conn:
        rid: int | None = None
        if run_id == "current":
            rid = await run_svc.current_run_id(conn)
        elif run_id != "all":
            rid = int(run_id)
        sql = "select id, run_id, event_type, payload, sim_time, real_time, scenario_id, correlation_id from sim_events where true"
        args: list[Any] = []
        if rid is not None:
            sql += " and run_id = %s"
            args.append(rid)
        if type:
            sql += " and event_type like %s"
            args.append(type + "%")
        if since_sim:
            sql += " and sim_time >= %s"
            args.append(since_sim)
        if cursor:
            sql += " and id < %s"
            args.append(int(cursor))
        sql += " order by id desc limit %s"
        args.append(limit)
        cur = await conn.execute(sql, args)  # noqa: S608 — все условия параметризованы
        rows = await cur.fetchall()
    items = [
        {
            "id": r[0],
            "run_id": r[1],
            "event_type": r[2],
            "payload": r[3],
            "sim_time": r[4],
            "real_time": r[5],
            "scenario_id": r[6],
            "correlation_id": r[7],
        }
        for r in rows
    ]
    return {"items": items, "next_cursor": str(rows[-1][0]) if len(rows) == limit else None}


@router.get("/api/sim/runs", summary="История запусков эмуляции (ТЗ 4.6)")
async def get_sim_runs(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> Any:
    async with await _conn() as conn:
        return {"items": await run_svc.list_runs(conn, limit)}


@router.post(
    "/api/sim/runs", summary="Создать и стартовать новый запуск (свободный или сценарный) с выбранным режимом сброса"
)
async def post_sim_runs(request: Request, body: dict[str, Any]) -> Any:
    if body.get("kind", "free") != "free" or body.get("reset_mode", "counters") == "baseline":
        raise NotImplementedYet("T-040")
    return await _sim(request).control("start", label=body.get("label") or "Запуск")


@router.get("/api/sim/runs/current", summary="Текущий запуск с живыми счётчиками (v_run_counters)")
async def get_sim_runs_current(request: Request) -> Any:
    async with await _conn() as conn:
        rid = await run_svc.current_run_id(conn)
        run = await run_svc.get_run(conn, rid) if rid else None
    if not run:
        raise HTTPException(status_code=404, detail="нет текущего запуска")
    return run


@router.get("/api/sim/runs/compare", summary="Сравнение двух запусков по метрикам 14.1/14.4 и расходу токенов")
async def get_sim_runs_compare(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs/{id}", summary="Запуск: параметры, счётчики, итоговые метрики")
async def get_sim_runs_id(request: Request, id: int) -> Any:  # noqa: A002
    async with await _conn() as conn:
        run = await run_svc.get_run(conn, id)
    if not run:
        raise HTTPException(status_code=404, detail="запуск не найден")
    return run


@router.delete("/api/sim/runs/{id}", summary="Удалить запуск вместе с данными (нельзя для baseline и текущего)")
async def delete_sim_runs_id(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post("/api/sim/runs/{id}/stop", summary="Завершить запуск (рассчитать summary, статус stopped)")
async def post_sim_runs_id_stop(request: Request, id: int) -> Any:  # noqa: A002
    sim = _sim(request)
    if sim.run_id != id:
        raise HTTPException(status_code=409, detail="остановить можно только текущий запуск")
    return await sim.control("stop")


@router.post("/api/sim/runs/{id}/resume", summary="Возобновить прерванный/приостановленный запуск с того же sim_time")
async def post_sim_runs_id_resume(request: Request, id: int) -> Any:  # noqa: A002
    sim = _sim(request)
    if sim.run_id != id:
        raise HTTPException(status_code=409, detail="возобновить можно только текущий запуск")
    return await sim.control("resume")


@router.post(
    "/api/sim/runs/{id}/archive",
    summary="Архивировать — экспорт в runs/<id>.json и удаление строк данных, summary сохраняется",
)
async def post_sim_runs_id_archive(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs/{id}/export", summary="Экспорт запуска (JSON с summary и агрегатами или CSV событий)")
async def get_sim_runs_id_export(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get(
    "/api/sim/baseline", summary="Состояние снимка базового состояния (путь, профиль, размер, контрольная сумма, дата)"
)
async def get_sim_baseline(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post(
    "/api/sim/baseline",
    summary="Пересоздать снимок baseline из текущего базового состояния (только когда нет активного запуска)",
)
async def post_sim_baseline(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post(
    "/api/sim/baseline/restore",
    summary="Откат к снимку baseline без старта нового запуска (режим обслуживания, ≤ 60 с для demo)",
)
async def post_sim_baseline_restore(request: Request) -> Any:
    raise NotImplementedYet("T-031")
