"""Аддитивный контракт demo-execution: только отдельные scenario-запуски, явное включение."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.api.common import agent_service
from app.api.scenarios import ScenarioRunRequest, run_scenario
from app.db.session import psycopg_dsn
from app.demo.execution import configuration, save

router = APIRouter(tags=["demo"])


class DemoExecutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    team_outcome: Literal["on_time", "late", "no_work", "failed", "recovered"] = "on_time"
    emulate_humans: bool = True
    auto_advance: bool = True


@router.get("/api/demo/execution", summary="Текущий demo-запуск и источник исполнения")
async def get_demo_execution(request: Request) -> Any:
    sim = getattr(request.app.state, "sim", None)
    rid = sim.run_id if sim else None
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        config = await configuration(conn, rid) if rid else {}
        incidents = []
        subject_ref = None
        if rid and config:
            row = await (
                await conn.execute("select public_id from signals where run_id=%s order by id desc limit 1", (rid,))
            ).fetchone()
            if row is None:
                row = await (
                    await conn.execute(
                        "select public_id from transcripts where run_id=%s order by id desc limit 1", (rid,)
                    )
                ).fetchone()
            subject_ref = row[0] if row else None
        if rid and config:
            incidents = [
                dict(zip(("id", "public_id", "status", "sla_breached", "resolution_summary"), r, strict=True))
                for r in await (
                    await conn.execute(
                        "select id,public_id,status,sla_breached,resolution_summary from incidents where run_id=%s order by id",
                        (rid,),
                    )
                ).fetchall()
            ]
    return {"run_id": rid, "subject_ref": subject_ref, "configuration": config, "incidents": incidents}


@router.post("/api/demo/execution", status_code=202, summary="Запустить изолированную эмуляцию команд и сотрудников")
async def post_demo_execution(request: Request, body: DemoExecutionBody) -> Any:
    lock = getattr(request.app.state, "demo_execution_lock", None)
    if lock is None:
        lock = request.app.state.demo_execution_lock = asyncio.Lock()
    async with lock:
        return await start_demo(request, body)


async def start_demo(request: Request, body: DemoExecutionBody) -> Any:
    agent_service(request)
    sim = getattr(request.app.state, "sim", None)
    if sim is None:
        raise HTTPException(503, "симулятор недоступен")
    # Один активный demo-run; не переключаем текущий запуск молча.
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        current = await configuration(conn, sim.run_id) if sim.run_id else {}
        if current.get("enabled"):
            raise HTTPException(409, "Сначала остановите текущую эмуляцию")
    await run_scenario(
        request,
        body.scenario_id,
        ScenarioRunRequest(label=f"[DEMO] {body.scenario_id} / {body.team_outcome}"),
        start_paused=True,
    )
    config = {**body.model_dump(), "enabled": True, "status": "running", "mode": "demo", "error": None}
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        await save(conn, sim.run_id, config)
    return await get_demo_execution(request)


@router.delete("/api/demo/execution", summary="Остановить эмуляцию, сохранив историю и ручные действия")
async def delete_demo_execution(request: Request) -> Any:
    lock = getattr(request.app.state, "demo_execution_lock", None)
    if lock is None:
        lock = request.app.state.demo_execution_lock = asyncio.Lock()
    async with lock:
        return await stop_demo(request)


async def stop_demo(request: Request) -> Any:
    sim = getattr(request.app.state, "sim", None)
    if sim and sim.run_id:
        async with sim._lock, await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
            config = await configuration(conn, sim.run_id)
            config.update(enabled=False, status="stopped")
            await save(conn, sim.run_id, config)
    return await get_demo_execution(request)
