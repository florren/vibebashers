"""Financial Impact Dashboard — изолированный срез запуска (ADR-0013)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.common import db, fetch_one, resolve_run_id
from app.economics import impact
from app.errors import Problem

router = APIRouter(tags=["finance"])


async def selected_run(conn: Any, run_id: str) -> int | None:
    if run_id == "all":
        raise Problem(422, "Выберите один запуск: current или числовой id")
    rid = await resolve_run_id(conn, run_id)
    if run_id != "current" and (rid is None or rid <= 0):
        raise Problem(422, "run_id должен быть положительным")
    if rid is not None and not await fetch_one(conn, "select id from sim_runs where id = %s", (rid,)):
        raise Problem(404, "Запуск не найден")
    return rid


@router.get("/api/v1/finance/impact/total", summary="Эффект запуска и отдельные сценарные оценки")
async def get_impact_total(
    period: Literal["live", "day", "week", "month", "custom"] = Query("live"),
    run_id: str = Query("current"),
    start_date: dt.datetime | None = Query(None),
    end_date: dt.datetime | None = Query(None),
    probability_percent: float = Query(100, ge=0, le=100, allow_inf_nan=False),
    fine_per_case_rub: float = Query(50000, ge=0, le=100000000, allow_inf_nan=False),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
) -> Any:
    if period == "custom" and (start_date is None or end_date is None):
        raise Problem(422, "Для произвольного периода нужны обе границы")
    async with db() as conn:
        async with conn.transaction():
            await conn.execute("set transaction isolation level repeatable read, read only")
            rid = await selected_run(conn, run_id)
            state = await fetch_one(conn, "select sim_time from sim_state where id = 1")
            now = state["sim_time"] if state else dt.datetime.now(dt.UTC)
            start, end = impact.bounds(period, now, start_date, end_date)
            res = await impact.total(
                conn,
                run_id=rid,
                period=period,
                start=start,
                end=end,
                probability=probability_percent,
                fine=fine_per_case_rub,
                offset=offset,
                limit=limit,
            )
    return JSONResponse(jsonable_encoder(res))


@router.get("/api/v1/finance/impact/incident/{incident_id}", summary="Обоснование эффекта решённого кейса")
async def get_impact_incident(
    incident_id: str,
    run_id: str = Query("current"),
    probability_percent: float = Query(100, ge=0, le=100, allow_inf_nan=False),
    fine_per_case_rub: float = Query(50000, ge=0, le=100000000, allow_inf_nan=False),
) -> Any:
    async with db() as conn:
        rid = await selected_run(conn, run_id)
        res = await impact.detail(conn, incident_id, rid, probability_percent, fine_per_case_rub)
    return JSONResponse(jsonable_encoder(res))
