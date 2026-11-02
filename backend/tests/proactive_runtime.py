"""Общий actual-main/CLI Mock harness; разрешены только ASGI и own PostgreSQL."""

import asyncio
import smtplib
import socket
import urllib.request
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.sim import scenarios
from tests.helpers import dsn


@asynccontextmanager
async def offline_main_runtime(database_url, monkeypatch, tmp_path):
    """Изолировать env/transport patches и завершить всех production actors до GET."""
    try:
        with monkeypatch.context() as patch:
            # Не загружаем inherited credentials, даже если они есть в runner environment.
            for name in (
                "GIGACHAT_AUTH_KEY_1",
                "GIGACHAT_AUTH_KEY_2",
                "OPENROUTER_API_KEY",
                "LOCAL_LLM_API_KEY",
                "TELEGRAM_BOT_TOKEN",
                "TGBOT_INTERNAL_SECRET",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "LOCAL_LLM_BASE_URL",
                "TGBOT_PUBLIC_BASE_URL",
                "GIGACHAT_CA_BUNDLE_FILE",
            ):
                patch.setenv(name, "")
            for name, value in {
                "TGBOT_ENABLED": "false",
                "MAILPIT_ENABLED": "false",
                "STT_PROVIDER": "none",
                "LLM_RECORD": "false",
                "LLM_CHAIN": "mock",
                "APP_SECRET": "synthetic-t039-runtime-secret",
                "GIGACHAT_BASE_URL": "https://gigachat.synthetic.invalid/v1",
                "GIGACHAT_OAUTH_URL": "https://oauth.synthetic.invalid",
                "GIGACHAT_VERIFY_SSL": "true",
                "OPENROUTER_BASE_URL": "https://router.synthetic.invalid/api/v1",
            }.items():
                patch.setenv(name, value)
            patch.setenv("APP_ENV", "dev")
            patch.setenv("ENV_FILE", "/dev/null")
            patch.setenv("LLM_PROVIDER", "mock")
            patch.setenv("DATABASE_URL", database_url)
            patch.setenv("LOG_PATH", str(tmp_path / "synthetic-runtime.jsonl"))
            patch.setenv("MAINTENANCE_CONTROL_DIR", str(tmp_path / "maintenance"))
            get_settings.cache_clear()
            external = []
            original = httpx.AsyncClient.send

            async def guarded(client, request, *args, **kwargs):
                if not isinstance(client._transport, httpx.ASGITransport):
                    external.append("non-ASGI HTTP")
                    raise AssertionError("Mock runtime не должен вызывать external HTTP")
                return await original(client, request, *args, **kwargs)

            patch.setattr(httpx.AsyncClient, "send", guarded)

            def forbidden(*_args, **_kwargs):
                external.append("sync HTTP/SMTP/DNS/socket")
                raise AssertionError("Разрешены только ASGI и собственный PostgreSQL")

            patch.setattr(httpx.Client, "send", forbidden)
            patch.setattr(smtplib, "SMTP", forbidden)
            patch.setattr(urllib.request, "urlopen", forbidden)
            pg = urlsplit(dsn(database_url))
            original_connect, original_connect_ex, original_resolve = (
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.getaddrinfo,
            )

            def connect(sock, address):
                if isinstance(address, tuple) and address[0] == pg.hostname and address[1] == (pg.port or 5432):
                    return original_connect(sock, address)
                return forbidden()

            def connect_ex(sock, address):
                if isinstance(address, tuple) and address[0] == pg.hostname and address[1] == (pg.port or 5432):
                    return original_connect_ex(sock, address)
                return forbidden()

            def resolve(host, *args, **kwargs):
                if host == pg.hostname:
                    return original_resolve(host, *args, **kwargs)
                return forbidden()

            patch.setattr(socket.socket, "connect", connect)
            patch.setattr(socket.socket, "connect_ex", connect_ex)
            patch.setattr(socket, "getaddrinfo", resolve)
            from app.main import create_app

            app = create_app()
            async with app.router.lifespan_context(app):
                assert app.state.agent is not None and app.state.agent.sim is app.state.sim
                assert app.state.twins is not None and app.state.ingest_poll is not None
                assert app.state.sim.full_execution is True
                assert app.state.llm_chain.offline_mode == "mock"
                assert "tgbot" not in app.state.runtime_components
                assert not get_settings().tgbot_enabled and not get_settings().mailpit_enabled
                yield app, external
                assert external == []
            assert external == []  # Cleanup также под egress bomb.
    finally:
        get_settings.cache_clear()


async def run_prepared_mass_case(app, database_url, monkeypatch):
    """Тот же production HTTP entry + journal worker, CLI30/outer45 без изменений."""
    from scripts import scenario_check as cli

    def cli_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "httpx", SimpleNamespace(AsyncClient=cli_client))
        async with asyncio.timeout(45):
            assert await cli.run_one(
                "http://synthetic.test", dsn(database_url), scenarios.get("mass_notifications"), 30
            )
    assert app.state.sim.run_id is not None
    return int(app.state.sim.run_id)
