"""Роутер тега `demo` (OpenAPI 1.4.0): статус, failover, прогон актива, кассеты (T-194, T-195 backend)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agent.prompts import prompt_version
from app.api.common import db, fetch_all
from app.api.scenarios import ScenarioRunRequest, post_scenarios_id_run
from app.config import get_settings
from app.db.session import psycopg_dsn
from app.llm.failover import ProviderChain, build_chain
from app.replay.store import CassetteStore
from app.sim import runs as run_svc
from app.sim.events import EventBus

router = APIRouter(tags=["demo"])


class FailoverBody(BaseModel):
    component: str
    to: str


class RecordBody(BaseModel):
    enabled: bool
    scenario_id: str | None = None


class PlayBody(BaseModel):
    asset_kind: str | None = None
    reset: str = "none"


def _modes(request: Request) -> dict[str, str]:
    state = getattr(request.app.state, "demo_modes", None)
    if not isinstance(state, dict):
        state = {"llm": "", "stt": "mic", "telegram": "online"}
        request.app.state.demo_modes = state
    return state


def _llm_mode(chain: ProviderChain | None, forced: str) -> str:
    if forced in ("live", "replay", "mock"):
        return forced
    names = chain.names if chain is not None else []
    for name in names:
        if name in ("gigachat", "openai_compatible", "openai_compat"):
            return "live"
        if name == "replay":
            return "replay"
        if name == "mock":
            return "mock"
    return "mock"


def _badge(llm_mode: str, stt_mode: str) -> str | None:
    if llm_mode == "mock":
        return "mock"
    if llm_mode == "replay":
        return "офлайн-кассета"
    if stt_mode == "file":
        return "STT: файл"
    if stt_mode == "transcript":
        return "STT: транскрипт"
    return None


async def _current_run() -> dict[str, Any] | None:
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        run_id = await run_svc.current_run_id(conn)
        if run_id is None:
            return None
        return await run_svc.get_run(conn, run_id)


async def _status(request: Request) -> dict[str, Any]:
    chain: ProviderChain | None = getattr(request.app.state, "llm_chain", None)
    modes = _modes(request)
    llm_mode = _llm_mode(chain, modes.get("llm") or "")
    stt_mode = modes.get("stt") or "mic"
    providers: list[dict[str, Any]] = []
    if chain is not None:
        for name in chain.names:
            providers.append({"component": "llm", "name": name, "healthy": True, "latency_ms": None, "detail": None})
    providers.append({"component": "stt", "name": stt_mode, "healthy": True, "latency_ms": None, "detail": None})
    try:
        current = await _current_run()
    except Exception:
        current = None
    return {
        "online": True,
        "llm_mode": llm_mode,
        "stt_mode": stt_mode if stt_mode in ("mic", "file", "transcript") else "mic",
        "providers": providers,
        "recording_cassettes": bool(chain is not None and chain.record_store is not None),
        "current_run": current,
        "badge_ru": _badge(llm_mode, stt_mode),
    }


def _apply_llm(request: Request, to: str) -> None:
    settings = get_settings()
    if to == "live":
        order = settings.llm_chain
    elif to == "replay":
        order = "replay,mock"
    elif to == "mock":
        order = "mock"
    else:
        raise HTTPException(status_code=422, detail="llm: ожидается live|replay|mock")
    cloned = settings.model_copy(update={"llm_chain": order, "llm_record": settings.llm_record})
    chain = build_chain(cloned)
    prev: ProviderChain | None = getattr(request.app.state, "llm_chain", None)
    if prev is not None and prev.record_store is not None and to == "live":
        chain.record_store = prev.record_store
        chain.scenario_id = prev.scenario_id
    request.app.state.llm_chain = chain
    agent = getattr(request.app.state, "agent", None)
    if agent is not None:
        agent.chain = chain


@router.get("/api/demo/status", summary="Состояние сети и провайдеров, текущие режимы LLM/STT")
async def get_demo_status(request: Request) -> Any:
    return await _status(request)


@router.post(
    "/api/demo/failover",
    summary="Ручное переключение режима (LLM live|replay|mock; STT mic|file|transcript; восстановить онлайн)",
)
async def post_demo_failover(request: Request, body: FailoverBody) -> Any:
    modes = _modes(request)
    chain: ProviderChain | None = getattr(request.app.state, "llm_chain", None)
    previous = modes.get(body.component) or (_llm_mode(chain, "") if body.component == "llm" else "")
    if body.component == "llm":
        _apply_llm(request, body.to)
        modes["llm"] = body.to
    elif body.component == "stt":
        if body.to not in ("mic", "file", "transcript"):
            raise HTTPException(status_code=422, detail="stt: ожидается mic|file|transcript")
        modes["stt"] = body.to
    elif body.component == "telegram":
        modes["telegram"] = body.to
    else:
        raise HTTPException(status_code=422, detail="component: llm|stt|telegram")
    await _emit_failover(request, body.component, previous or "unknown", body.to)
    return await _status(request)


async def _emit_failover(request: Request, component: str, src: str, dst: str) -> None:
    sim = getattr(request.app.state, "sim", None)
    run_id = getattr(sim, "run_id", None) if sim is not None else None
    if run_id is None:
        return
    clock = getattr(sim, "clock", None)
    sim_time = getattr(clock, "sim_time", None) or dt.datetime.now(dt.UTC)
    payload = {
        "event_type": "demo.failover",
        "component": component,
        "from": src,
        "to": dst,
        "reason": "manual",
        "automatic": False,
    }
    try:
        async with db() as conn:
            await EventBus(conn, strict=False).emit(int(run_id), "demo.failover", payload, sim_time)
    except Exception:
        return


@router.post(
    "/api/demo/play/{scenario_id}",
    summary="Запустить предзаписанный вход сценария (пост сценария 8, аудио/транскрипт сценария 9)",
    status_code=202,
)
async def post_demo_play_scenario_id(request: Request, scenario_id: str, body: PlayBody | None = None) -> Any:
    body = body or PlayBody()
    reset = "counters" if body.reset == "none" else body.reset
    started = await post_scenarios_id_run(
        request, scenario_id, ScenarioRunRequest(reset_mode=reset, label=f"демо {scenario_id}")
    )
    run = started.get("run") or {}
    run_id = run.get("id")
    post_id = None
    session_id = None
    agent_run_id = None
    if run_id is not None:
        async with db() as conn:
            post = await conn.execute(
                "select id from external_posts where run_id = %s order by id desc limit 1", (run_id,)
            )
            prow = await post.fetchone()
            post_id = int(prow["id"]) if prow else None
            sess = await conn.execute(
                "select id from audio_sessions where run_id = %s order by id desc limit 1", (run_id,)
            )
            srow = await sess.fetchone()
            session_id = int(srow["id"]) if srow else None
            ag = await conn.execute(
                "select id from agent_runs where sim_run_id = %s order by id desc limit 1", (run_id,)
            )
            arow = await ag.fetchone()
            agent_run_id = int(arow["id"]) if arow else None
    if started.get("transcript_id") and session_id is None:
        session_id = None
    return {"post_id": post_id, "session_id": session_id, "agent_run_id": agent_run_id}


@router.get("/api/demo/assets", summary="Предзаписанные активы (аудио, транскрипты, посты, кассеты)")
async def get_demo_assets(request: Request, kind: str | None = None, scenario_id: str | None = None) -> Any:
    sql = "select id, kind, scenario_id, title_ru, path, checksum, duration_ms from demo_assets where true"
    args: list[Any] = []
    if kind:
        sql += " and kind = %s"
        args.append(kind)
    if scenario_id:
        sql += " and scenario_id = %s"
        args.append(scenario_id)
    sql += " order by id"
    async with db() as conn:
        rows = await fetch_all(conn, sql, args)
    return [{**row, "has_reference": bool(row.get("checksum"))} for row in rows]


@router.get("/api/cassettes", summary="Кассеты replay (сводка по сценариям и моделям)")
async def get_cassettes(request: Request) -> Any:
    store = CassetteStore(get_settings().cassettes_dir)
    return store.summaries(prompt_version())


@router.post("/api/cassettes/record", summary="Включить/выключить запись кассет (LLM_RECORD) для текущей сессии показа")
async def post_cassettes_record(request: Request, body: RecordBody) -> Any:
    chain: ProviderChain | None = getattr(request.app.state, "llm_chain", None)
    if chain is None:
        chain = build_chain(get_settings())
        request.app.state.llm_chain = chain
    if body.enabled:
        chain.record_store = CassetteStore(get_settings().cassettes_dir)
        chain.scenario_id = body.scenario_id
        chain.prompt_version = prompt_version()
    else:
        chain.record_store = None
        chain.scenario_id = None
    return {"enabled": body.enabled, "scenario_id": body.scenario_id}
