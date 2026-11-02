"""FastAPI-приложение CX Pulse Control (T-004): конфиг, structlog, problem+json, роутеры по тегам OpenAPI, WebSocket, LISTEN/NOTIFY."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb

from app import __version__
from app import api as api_pkg
from app.abs.service import backfill_ledger
from app.agent.runner import AgentService
from app.bench.service import BenchService
from app.config import get_settings
from app.db.session import psycopg_dsn
from app.errors import Problem, install_error_handlers
from app.llm.failover import ProviderChain, build_chain, default_profile
from app.llm.gigachat import GigaChatProvider
from app.llm.openai_compat import OpenAICompatProvider, is_openrouter, openrouter_deactivation_plan
from app.llm.roles import refresh as refresh_roles
from app.logging import configure_logging, get_logger
from app.observability.http import RequestLogMiddleware
from app.realtime import ws as ws_module
from app.realtime.notify import bridge
from app.sim.engine import Simulator
from app.sim.twins import TwinService
from app.stt import audio_ws

log = get_logger(__name__)


async def _sync_openrouter_models(chain: ProviderChain) -> None:
    """Нет id в каталоге OpenRouter — профиль is_active=false. Чужой base_url, ошибка GET и пустой список не гасят."""
    prov = next((p for p in chain.providers if isinstance(p, OpenAICompatProvider)), None)
    if prov is None or not is_openrouter(prov.base_url):
        return
    plan = await openrouter_deactivation_plan(prov)
    if not plan:
        return
    try:
        async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
            for item in plan:
                log.warning(
                    "openrouter_model_missing",
                    model=item["model"],
                    suggested_model=item["suggested_model"],
                )
                await conn.execute(
                    "update llm_profiles set is_active = false, "
                    "extra = coalesce(extra, '{}'::jsonb) || %s "
                    "where provider = 'openai_compatible' and model = %s",
                    (Jsonb({"suggested_model": item["suggested_model"]}), item["model"]),
                )
            await conn.commit()
    except Exception as exc:
        log.warning("openrouter_profile_sync_failed", error=str(exc)[:200])


async def _abs_backfill() -> None:
    """Mock-АБС: проводки для операций, появившихся без проводок (сид/старые запуски) — идемпотентно, при старте."""
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        done = await backfill_ledger(conn)
        await conn.commit()
    if any(done.values()):
        log.info("abs_backfill", **done)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.app_env, s.log_path if (s.log_jsonl and not s.is_test) else None, s.log_jsonl_level)
    app.state.llm_chain = build_chain(s)
    app.state.llm_profile = default_profile(s)
    if not s.is_test:
        await refresh_roles(app, s)
        for provider in app.state.llm_chain.providers:
            if isinstance(provider, GigaChatProvider):
                await provider.prepare(list(app.state.llm_chain.role_profiles.values()))
    if not s.is_test and any(p.name == "openai_compatible" for p in app.state.llm_chain.providers):
        await _sync_openrouter_models(app.state.llm_chain)
    log.info(
        "startup",
        env=s.app_env,
        profile=s.profile,
        llm=s.llm_provider,
        chain=app.state.llm_chain.names,
        version=__version__,
    )
    app.state.bench = BenchService()
    app.state.sim = None
    app.state.agent = None
    app.state.twins = None
    poll_stop: asyncio.Event | None = None
    if not s.is_test:
        from app.ingest.sources import polling_worker

        poll_stop = asyncio.Event()
        app.state.ingest_poll = asyncio.create_task(polling_worker(poll_stop))
        bridge.start()
        app.state.agent = AgentService(app.state.llm_chain, app.state.llm_profile)
        app.state.agent.start()
        app.state.twins = TwinService(app.state.llm_chain, app.state.llm_profile)
        app.state.twins.start()
        sim = Simulator(seed=s.sim_seed)
        sim.full_execution = True
        try:
            await sim.load_state()
            app.state.sim = sim
            await _abs_backfill()
        except Exception as exc:  # БД недоступна — API симулятора ответит 503, остальное работает
            log.warning("sim_init_failed", error=str(exc)[:200])
    demo_task = public_task = None
    if not s.is_test:
        from app.demo.execution import public_worker
        from app.demo.execution import worker as demo_worker

        demo_task = asyncio.create_task(demo_worker(app), name="demo-execution")
        public_task = asyncio.create_task(public_worker(app), name="public-execution")
    yield
    for execution_task in (demo_task, public_task):
        if execution_task:
            execution_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution_task
    await app.state.bench.stop()
    if app.state.twins is not None:
        await app.state.twins.stop()
    if poll_stop is not None:
        poll_stop.set()
        task = getattr(app.state, "ingest_poll", None)
        if task is not None:
            await task
    if app.state.agent is not None:
        await app.state.agent.stop()
    if app.state.sim is not None:
        await app.state.sim.shutdown()
    await bridge.stop()
    for provider in app.state.llm_chain.providers:
        if isinstance(provider, (GigaChatProvider, OpenAICompatProvider)):
            await provider.aclose()


def include_api_routers(app: FastAPI) -> list[str]:
    names = []
    for m in sorted(pkgutil.iter_modules(api_pkg.__path__), key=lambda x: x.name):
        if m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"app.api.{m.name}")
        router = getattr(mod, "router", None)
        if router is not None:
            app.include_router(router)
            names.append(m.name)
    return names


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="CX Pulse Control API",
        version="1.4.0",
        lifespan=lifespan,
        docs_url="/docs" if s.app_env != "prod" else None,
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True
    )
    app.add_middleware(RequestLogMiddleware)
    install_error_handlers(app)
    include_api_routers(app)
    app.include_router(ws_module.router)
    app.include_router(audio_ws.router)
    mount_frontend(app, s.frontend_dist)
    # FastAPI лениво компилирует included routes при первом HTTP. Готовим только
    # route/dependency/schema metadata до readiness, без вызова handlers/DB/LLM.
    app.openapi()
    return app


def mount_frontend(app: FastAPI, dist: str | None) -> None:
    """Раздача собранного фронта (frontend/dist) с SPA-фолбэком. Если каталога нет — ничего не делаем (dev: vite proxy)."""
    root = Path(dist) if dist else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    index = root / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "ws/", "docs", "openapi.json")):
            raise Problem(404, "Не найдено")
        candidate = root / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
