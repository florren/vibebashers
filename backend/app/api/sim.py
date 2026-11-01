"""Управление симулятором, история запусков, baseline и сохранённые итоги (T-040/T-042)."""

from __future__ import annotations

import contextlib
import datetime as dt
import tempfile
from collections.abc import Iterator
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.db.session import psycopg_dsn
from app.llm.run_profiles import validate_main_profile
from app.sim import baseline as baseline_svc
from app.sim import run_lifecycle, run_summary
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


class SimRunCreate(BaseModel):
    kind: Literal["free", "scenario"]
    scenario_id: str | None = None
    label: str | None = None
    seed: int | None = None
    reset_mode: Literal["none", "counters", "baseline"] = "counters"
    speed_preset: Literal["demo_5min", "day_12min", "realtime"] | None = None
    llm_profile_id: int | None = None


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
    sim.full_execution = True
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
async def get_sim_runs(
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = None,
    kind: Literal["baseline", "free", "scenario", "live"] | None = None,
    cursor: int | None = Query(default=None, ge=1),
) -> Any:
    statuses = status.split(",") if status else None
    if statuses and any(
        value not in {"running", "paused", "interrupted", "completed", "stopped", "archived"} for value in statuses
    ):
        raise HTTPException(422, "неизвестный статус запуска")
    async with await _conn() as conn:
        rows = await run_svc.list_runs(conn, limit + 1, statuses=statuses, kind=kind, cursor=cursor)
    return {"items": rows[:limit], "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None}


async def _ensure_dump_allowed(request: Request) -> Simulator:
    sim = _sim(request)
    if sim.clock.running or sim.run_status in ("running", "paused", "interrupted"):
        raise HTTPException(status_code=409, detail="нельзя пересоздать снимок при активном запуске")
    async with await _conn() as conn:
        rid = await run_svc.current_run_id(conn)
        if rid:
            run = await run_svc.get_run(conn, rid)
            if run and run["status"] in ("running", "paused", "interrupted"):
                raise HTTPException(status_code=409, detail="нельзя пересоздать снимок при активном запуске")
    return sim


async def _restore_baseline(request: Request) -> str:
    sim = _sim(request)
    if sim.clock.running:
        await sim.control("pause")
    conn = await sim.connect()
    try:
        job_id = await baseline_svc.restore(conn, pause=sim.clock.running or sim.run_status == "paused")
    except baseline_svc.BaselineUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except baseline_svc.BaselineToolingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        if sim.conn and not sim.conn.closed:
            with contextlib.suppress(Exception):
                await sim.conn.close()
        sim.conn = None
    await sim.reload_after_restore()
    return job_id


@router.post(
    "/api/sim/runs",
    summary="Создать и стартовать новый запуск (свободный или сценарный) с выбранным режимом сброса",
    status_code=202,
)
async def post_sim_runs(request: Request, body: SimRunCreate) -> Any:
    if body.kind == "scenario":
        from app.api.scenarios import ScenarioRunRequest, run_scenario

        if not body.scenario_id:
            raise HTTPException(422, "scenario_id обязателен для сценарного запуска")
        result = await run_scenario(request, body.scenario_id, ScenarioRunRequest(**body.model_dump()))
        return result["run"]
    if body.scenario_id:
        raise HTTPException(422, "scenario_id допустим только для сценарного запуска")
    if body.llm_profile_id is not None:
        try:
            async with await _conn() as conn:
                await validate_main_profile(conn, body.llm_profile_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if body.reset_mode == "baseline":
        if not baseline_svc.info()["available"]:
            raise HTTPException(status_code=409, detail="снимок baseline ещё не создан")
        await _restore_baseline(request)
    sim = _sim(request)
    try:
        values = body.model_dump(exclude_none=True)
        values["label"] = body.label or "Запуск"
        await sim.control("start", **values)
        if body.speed_preset:
            await sim.control("set_preset", preset=body.speed_preset)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if sim.run_id is None:
        raise RuntimeError("созданный запуск не имеет run_id")
    async with await _conn() as conn:
        return await run_svc.get_run(conn, sim.run_id)


@router.get("/api/sim/runs/current", summary="Текущий запуск с живыми счётчиками (v_run_counters)")
async def get_sim_runs_current(request: Request) -> Any:
    async with await _conn() as conn:
        rid = await run_svc.current_run_id(conn)
        run = await run_svc.get_run(conn, rid) if rid else None
    if not run:
        raise HTTPException(status_code=404, detail="нет текущего запуска")
    return run


_numeric_diff = run_summary.numeric_diff


@router.get("/api/sim/runs/compare", summary="Сравнение двух запусков по метрикам 14.1/14.4 и расходу токенов")
async def get_sim_runs_compare(a: int, b: int) -> Any:
    async with await _conn() as conn, conn.transaction():
        await conn.execute("set transaction isolation level repeatable read read only")
        left = await run_svc.get_run(conn, a)
        right = await run_svc.get_run(conn, b)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="запуск не найден")
        for run in (left, right):
            if (
                not isinstance(run.get("summary"), dict)
                or run["summary"].get("summary_version") != run_summary.SUMMARY_VERSION
            ):
                run["summary"] = await run_summary.build_summary(conn, int(run["id"]))
    return {"a": left, "b": right, "diff": _numeric_diff(left["summary"], right["summary"])}


@router.get("/api/sim/runs/{id}", summary="Запуск: параметры, счётчики, итоговые метрики")
async def get_sim_runs_id(request: Request, id: int) -> Any:  # noqa: A002
    async with await _conn() as conn:
        run = await run_svc.get_run(conn, id)
    if not run:
        raise HTTPException(status_code=404, detail="запуск не найден")
    return run


@router.delete("/api/sim/runs/{id}", summary="Удалить запуск вместе с данными (нельзя для baseline и текущего)")
async def delete_sim_runs_id(id: int) -> Response:  # noqa: A002
    try:
        async with await _conn() as conn:
            await run_lifecycle.delete(conn, id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (run_lifecycle.RunConflict, psycopg.errors.LockNotAvailable) as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)


@router.post("/api/sim/runs/{id}/stop", summary="Завершить запуск (рассчитать summary, статус stopped)")
async def post_sim_runs_id_stop(request: Request, id: int) -> Any:  # noqa: A002
    sim = _sim(request)
    if sim.run_id != id:
        raise HTTPException(status_code=409, detail="остановить можно только текущий запуск")
    await sim.control("stop")
    async with await _conn() as conn:
        return await run_svc.get_run(conn, id)


@router.post("/api/sim/runs/{id}/resume", summary="Возобновить прерванный/приостановленный запуск с того же sim_time")
async def post_sim_runs_id_resume(request: Request, id: int) -> Any:  # noqa: A002
    sim = _sim(request)
    if sim.run_id != id:
        raise HTTPException(status_code=409, detail="возобновить можно только текущий запуск")
    try:
        await sim.control("resume")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    async with await _conn() as conn:
        return await run_svc.get_run(conn, id)


@router.post(
    "/api/sim/runs/{id}/archive",
    summary="Архивировать — экспорт в runs/<id>.json и удаление строк данных, summary сохраняется",
)
async def post_sim_runs_id_archive(id: int) -> Any:  # noqa: A002
    try:
        async with await _conn() as conn:
            return await run_lifecycle.archive(conn, id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (run_lifecycle.RunConflict, psycopg.errors.LockNotAvailable) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/sim/runs/{id}/export", summary="Экспорт запуска (JSON с summary и агрегатами или CSV событий)")
async def get_sim_runs_id_export(id: int, format: Literal["json", "csv"] = "json") -> Any:  # noqa: A002
    async with await _conn() as conn, conn.transaction():
        await conn.execute("set transaction isolation level repeatable read read only")
        run = await run_svc.get_run(conn, id)
        if run is None:
            raise HTTPException(status_code=404, detail="запуск не найден")
        if run["status"] == "archived":
            if format == "csv":
                raise HTTPException(409, "События удалены при архивации; доступен сохранённый JSON")
            try:
                exported = run_lifecycle.read_archive(run)
            except run_lifecycle.RunConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            return JSONResponse(
                exported,
                headers={"Content-Disposition": f'attachment; filename="run-{id}.json"'},
            )
        if format == "json":
            out = await run_summary.export_json(conn, id)
            return JSONResponse(
                jsonable_encoder(out), headers={"Content-Disposition": f'attachment; filename="run-{id}.json"'}
            )
        # Буфер до отправки заголовков: единый snapshot, ограниченная RAM, курсор закрыт до disconnect.
        spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+", encoding="utf-8", newline="")
        try:
            async for chunk in run_summary.csv_events(conn, id):
                spool.write(chunk)
            spool.seek(0)
        except BaseException:
            spool.close()
            raise

    def chunks() -> Iterator[str]:
        try:
            while chunk := spool.read(64 * 1024):
                yield chunk
        finally:
            spool.close()

    return StreamingResponse(
        chunks(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="run-{id}.csv"'},
    )


@router.get(
    "/api/sim/baseline", summary="Состояние снимка базового состояния (путь, профиль, размер, контрольная сумма, дата)"
)
async def get_sim_baseline(request: Request) -> Any:
    return baseline_svc.info()


@router.post(
    "/api/sim/baseline",
    summary="Пересоздать снимок baseline из текущего базового состояния (только когда нет активного запуска)",
    status_code=202,
)
async def post_sim_baseline(request: Request) -> Any:
    await _ensure_dump_allowed(request)
    sim = _sim(request)
    conn = await sim.connect()
    try:
        result = await baseline_svc.dump(conn)
    except baseline_svc.BaselineToolingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        await conn.commit()
    return result


@router.post(
    "/api/sim/baseline/restore",
    summary="Откат к снимку baseline без старта нового запуска (режим обслуживания, ≤ 60 с для demo)",
    status_code=202,
)
async def post_sim_baseline_restore(request: Request) -> Any:
    if not baseline_svc.info()["available"]:
        raise HTTPException(status_code=409, detail="снимок baseline ещё не создан")
    job_id = await _restore_baseline(request)
    return {"job_id": job_id}
