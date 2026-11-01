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
from app.llm.openai_compat import OpenAICompatProvider, openrouter_deactivation_plan
from app.llm.roles import refresh as refresh_roles
from app.logging import configure_logging, get_logger
from app.observability.http import RequestLogMiddleware
from app.realtime import ws as ws_module
from app.realtime.notify import bridge
from app.sim.engine import Simulator
from app.sim.maintenance import MaintenanceCoordinator, MaintenanceMiddleware, start_daemon
from app.sim.maintenance_control import ControlError, MaintenanceControl
from app.sim.maintenance_db import DatabaseBoundary
from app.sim.twins import TwinService
from app.stt import audio_ws

log = get_logger(__name__)


async def _sync_openrouter_models(chain: ProviderChain) -> None:
    """Нет id в каталоге OpenRouter — профиль is_active=false. Чужой base_url, ошибка GET и пустой список не гасят."""
    prov = next((p for p in chain.providers if isinstance(p, OpenAICompatProvider)), None)
    if prov is None or "openrouter.ai" not in prov.base_url:
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


async def _start_runtime(app: FastAPI, components: set[str]) -> None:
    """Создаёт только runtime-компоненты, которыми владеет lifespan."""
    with app.state.maintenance.bind():
        if "agent" in components:
            app.state.agent = AgentService(app.state.llm_chain, app.state.llm_profile)
            app.state.agent.enabled = getattr(app.state, "maintenance_agent_enabled", True)
            app.state.agent.start()
        if "twins" in components:
            app.state.twins = TwinService(app.state.llm_chain, app.state.llm_profile)
            app.state.twins.start()
        if "poll" in components:
            from app.ingest.sources import polling_worker

            app.state.poll_stop = asyncio.Event()
            app.state.ingest_poll = start_daemon(lambda: polling_worker(app.state.poll_stop), name="ingest-poll")
        if "demo" in components:
            from app.demo.execution import worker

            app.state.demo_task = start_daemon(lambda: worker(app), name="demo-execution")
        if "public" in components:
            from app.demo.execution import public_worker

            app.state.public_task = start_daemon(lambda: public_worker(app), name="public-execution")
    app.state.runtime_components = components


async def _park_runtime(app: FastAPI) -> None:
    """Вызывается после drain; активные seed/audio до этого отклоняют restore."""
    components = set(getattr(app.state, "runtime_components", set()))
    if not hasattr(app.state, "maintenance_saved_components"):
        app.state.maintenance_saved_components = components
        app.state.maintenance_agent_enabled = getattr(getattr(app.state, "agent", None), "enabled", True)
    sim = getattr(app.state, "sim", None)
    if sim is not None and hasattr(sim, "shutdown"):
        if sim.clock.running:
            await sim.control("pause")
        await sim.shutdown()
    for name in ("demo_task", "public_task"):
        task = getattr(app.state, name, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            setattr(app.state, name, None)
    bench = getattr(app.state, "bench", None)
    if bench is not None:
        await bench.stop()
    if "twins" in components and app.state.twins is not None:
        await app.state.twins.stop()
        app.state.twins = None
    if "poll" in components:
        app.state.poll_stop.set()
        task = getattr(app.state, "ingest_poll", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        app.state.ingest_poll = None
    if "agent" in components and app.state.agent is not None:
        await app.state.agent.stop()
        app.state.agent = None
    from app.db.session import get_engine

    await get_engine().dispose()
    app.state.runtime_components = set()


async def _resume_runtime(app: FastAPI) -> None:
    if getattr(app.state, "maintenance_startup_recovery", False):
        await _prepare_runtime_profiles(app)
        if not get_settings().is_test:
            await _abs_backfill()
            bridge.start()
        app.state.maintenance_startup_recovery = False
    components = set(getattr(app.state, "maintenance_saved_components", set()))
    # Завершённые benchmark записи/ключи не должны ссылаться на переиспользованные ID.
    app.state.bench = BenchService()
    await _start_runtime(app, components)
    if hasattr(app.state, "maintenance_saved_components"):
        del app.state.maintenance_saved_components


async def _initialize_maintenance(app: FastAPI) -> bool:
    coordinator = app.state.maintenance
    control = coordinator.control
    if control is None:
        return False
    try:
        if control.read() is None:
            # Bootstrap не пересоздаёт уже существующий failed/corrupt marker.
            await coordinator.boundary.acquire()
            try:
                control.initialize_missing()
            finally:
                await coordinator.boundary.release()
        control.require_idle()
        return False
    except ControlError:
        coordinator.phase = "failed"
        coordinator.failure = "IncompleteMaintenance"
        coordinator._ready.clear()
        log.error("baseline_maintenance_recovery_required")
        return True


async def _prepare_runtime_profiles(app: FastAPI) -> None:
    s = get_settings()
    if not s.is_test:
        await refresh_roles(app, s)
        for provider in app.state.llm_chain.providers:
            if isinstance(provider, GigaChatProvider):
                await provider.prepare(list(app.state.llm_chain.role_profiles.values()))
    if not s.is_test and any(p.name == "openai_compatible" for p in app.state.llm_chain.providers):
        await _sync_openrouter_models(app.state.llm_chain)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.app_env, s.log_path if (s.log_jsonl and not s.is_test) else None, s.log_jsonl_level)
    recovering = await _initialize_maintenance(app)
    app.state.llm_chain = build_chain(s)
    app.state.llm_profile = default_profile(s)
    if not recovering:
        await _prepare_runtime_profiles(app)
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
    app.state.runtime_components = set()
    if recovering:
        app.state.sim = Simulator(seed=s.sim_seed)
        app.state.sim.full_execution = True
        app.state.maintenance_saved_components = (
            {"agent", "twins", "poll", "demo", "public"} if not s.is_test else set()
        )
        app.state.maintenance_startup_recovery = True
    if not s.is_test and not recovering:
        bridge.start()
        sim = Simulator(seed=s.sim_seed)
        sim.full_execution = True
        try:
            await sim.load_state()
            app.state.sim = sim
            await _abs_backfill()
        except Exception as exc:  # БД недоступна — API симулятора ответит 503, остальное работает
            log.warning("sim_init_failed", error=str(exc)[:200])
    if not s.is_test and not recovering:
        await _start_runtime(app, {"agent", "twins", "poll", "demo", "public"})
    yield
    try:
        await app.state.maintenance.join_restore()
    except Exception as exc:
        log.warning("restore_failed_at_shutdown", error_type=type(exc).__name__)
    await _park_runtime(app)
    if app.state.maintenance.boundary is not None:
        await app.state.maintenance.boundary.release()
    await bridge.stop()
    for provider in app.state.llm_chain.providers:
        if isinstance(provider, GigaChatProvider):
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
    app.state.maintenance = MaintenanceCoordinator(boundary=DatabaseBoundary(), control=MaintenanceControl())
    app.state.maintenance_park = lambda: _park_runtime(app)
    app.state.maintenance_resume = lambda: _resume_runtime(app)
    app.add_middleware(MaintenanceMiddleware, coordinator=app.state.maintenance)
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True
    )
    app.add_middleware(RequestLogMiddleware)
    install_error_handlers(app)
    include_api_routers(app)
    app.include_router(ws_module.router)
    app.include_router(audio_ws.router)
    mount_frontend(app, s.frontend_dist)
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
