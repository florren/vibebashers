"""Main lifespan + реальные actors, synthetic own DB/Mock и HTTP egress bomb."""

import asyncio
import smtplib
import socket
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import psycopg
import pytest

from app.config import get_settings
from app.sim import scenarios
from app.sim.proactive_scenario import case
from tests.helpers import dsn
from tests.integration.test_proactive_prepare import mass_seeded as mass_seeded


@pytest.mark.asyncio
async def test_main_runtime_executes_scripted_native_phases_with_all_actors_and_no_external_http(
    mass_seeded, monkeypatch, tmp_path
):
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
        monkeypatch.setenv(name, "")
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
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ENV_FILE", "/dev/null")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_URL", mass_seeded)
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "synthetic-runtime.jsonl"))
    monkeypatch.setenv("MAINTENANCE_CONTROL_DIR", str(tmp_path / "maintenance"))
    get_settings.cache_clear()
    external = []
    original = httpx.AsyncClient.send

    async def guarded(client, request, *args, **kwargs):
        if not isinstance(client._transport, httpx.ASGITransport):
            external.append("non-ASGI HTTP")
            raise AssertionError("Mock runtime не должен вызывать external HTTP")
        return await original(client, request, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", guarded)

    def forbidden(*_args, **_kwargs):
        external.append("sync HTTP/SMTP/DNS/socket")
        raise AssertionError("Разрешены только ASGI и собственный PostgreSQL")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    pg = urlsplit(dsn(mass_seeded))
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

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    from app.main import create_app

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            assert app.state.agent is not None and app.state.agent.sim is app.state.sim
            assert app.state.twins is not None and app.state.ingest_poll is not None
            assert app.state.sim.full_execution is True
            assert app.state.llm_chain.offline_mode == "mock"
            assert "tgbot" not in app.state.runtime_components
            assert not get_settings().tgbot_enabled and not get_settings().mailpit_enabled
            from scripts import scenario_check as cli

            # Подменён только transport reference самого CLI, не shared httpx
            # module: остальные actors всё ещё находятся под egress Bomb.
            def cli_client(**kwargs):
                return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

            monkeypatch.setattr(cli, "httpx", SimpleNamespace(AsyncClient=cli_client))
            async with asyncio.timeout(45):
                assert await cli.run_one(
                    "http://synthetic.test", dsn(mass_seeded), scenarios.get("mass_notifications"), 30
                )
            run = app.state.sim.run_id
            async with await psycopg.AsyncConnection.connect(dsn(mass_seeded)) as conn:
                context = await case(conn, run)
                assert context is not None and "completed" in context.events
                result = await scenarios.evaluate(conn, scenarios.get("mass_notifications"), run)
                assert result["passed"], result["checks"]
                assert result["counts"]["affected"] == 120
                assert result["counts"]["notified_before_first_complaint"] >= 90
                assert result["counts"]["complaints"] == result["counts"]["deduplicated"] == 30
                assert result["counts"]["care_positive"] >= 90
                assert (
                    await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()
                ) == (31,)
                assert (
                    await (
                        await conn.execute("select count(*) from v_cabinet_signal_facts where run_id=%s", (run,))
                    ).fetchone()
                ) == (30,)
                assert (
                    await (await conn.execute("select count(*) from ledger_entries where run_id=%s", (run,))).fetchone()
                ) == (0,)
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from human_decisions where sim_run_id=%s and decision is null", (run,)
                        )
                    ).fetchone()
                )[0] >= 1
                assert (await (await conn.execute("select status from sim_runs where id=%s", (run,))).fetchone()) == (
                    "paused",
                )
                assert app.state.sim.clock.sim_time == context.observed_at
            assert external == []
        assert external == []  # Cleanup тоже не получает egress exception.
    finally:
        get_settings.cache_clear()
