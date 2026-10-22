"""FastAPI-приложение CX Pulse Control (T-004): конфиг, structlog, problem+json, роутеры по тегам OpenAPI, WebSocket, LISTEN/NOTIFY."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app import api as api_pkg
from app.config import get_settings
from app.errors import install_error_handlers
from app.llm.failover import build_chain, default_profile
from app.logging import configure_logging, get_logger
from app.realtime import ws as ws_module
from app.realtime.notify import bridge

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.app_env)
    app.state.llm_chain = build_chain(s)
    app.state.llm_profile = default_profile(s)
    log.info(
        "startup",
        env=s.app_env,
        profile=s.profile,
        llm=s.llm_provider,
        chain=app.state.llm_chain.names,
        version=__version__,
    )
    if not s.is_test:
        bridge.start()
    yield
    await bridge.stop()


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
    install_error_handlers(app)
    include_api_routers(app)
    app.include_router(ws_module.router)
    return app


app = create_app()
