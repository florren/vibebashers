"""Lifecycle transport: только fake sender, без Telegram/DB/LLM."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from app import main
from app.sim.maintenance import MaintenanceCoordinator
from app.tgbot import delivery


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("recovering", [False, True])
async def test_production_lifespan_keeps_bot_flag_across_normal_start_and_restore(monkeypatch, enabled, recovering):
    # Все остальные actors/IO — fakes: проверяем actual lifespan wiring, не Telegram.
    settings = SimpleNamespace(
        app_env="test",
        is_test=False,
        log_jsonl=False,
        log_path=None,
        log_jsonl_level="INFO",
        profile="lite",
        llm_provider="mock",
        sim_seed=42,
        tgbot_enabled=enabled,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "configure_logging", Mock())
    monkeypatch.setattr(main, "_initialize_maintenance", AsyncMock(return_value=recovering))
    monkeypatch.setattr(main, "build_chain", lambda _: SimpleNamespace(names=["mock"], providers=[]))
    monkeypatch.setattr(main, "default_profile", lambda _: object())
    monkeypatch.setattr(main, "_prepare_runtime_profiles", AsyncMock())
    monkeypatch.setattr(main, "BenchService", lambda: object())
    monkeypatch.setattr(
        main, "Simulator", lambda **kwargs: SimpleNamespace(full_execution=False, load_state=AsyncMock())
    )
    monkeypatch.setattr(main, "bridge", SimpleNamespace(start=Mock(), stop=AsyncMock()))
    monkeypatch.setattr(main, "_abs_backfill", AsyncMock())
    start, park = AsyncMock(), AsyncMock()
    monkeypatch.setattr(main, "_start_runtime", start)
    monkeypatch.setattr(main, "_park_runtime", park)
    monkeypatch.setattr(main, "clear_runtime_keys", Mock())
    app = FastAPI()
    app.state.maintenance = SimpleNamespace(join_restore=AsyncMock(), boundary=None)
    async with main.lifespan(app):
        if recovering:
            start.assert_not_awaited()
            assert ("tgbot" in app.state.maintenance_saved_components) is enabled
            assert app.state.maintenance_startup_recovery is True
        else:
            start.assert_awaited_once()
            assert ("tgbot" in start.await_args.args[1]) is enabled
            assert start.await_args.kwargs == {"startup_recovery": True}
    park.assert_awaited_once_with(app)


async def test_maintenance_parks_and_restarts_only_owned_telegram_task(monkeypatch):
    app = FastAPI()
    app.state.maintenance = MaintenanceCoordinator()
    entered, closed = asyncio.Event(), asyncio.Event()
    generations = []

    async def worker():
        generations.append(asyncio.current_task())
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(delivery, "worker", worker)
    monkeypatch.setattr("app.db.session.get_engine", lambda: engine)
    await main._start_runtime(app, {"tgbot"})
    await asyncio.wait_for(entered.wait(), 2)
    first = app.state.tgbot_task
    await main._park_runtime(app)
    assert first.cancelled() and closed.is_set()
    assert app.state.tgbot_task is None and app.state.runtime_components == set()
    assert app.state.maintenance_saved_components == {"tgbot"}
    engine.dispose.assert_awaited_once()
    entered.clear()
    await main._start_runtime(app, app.state.maintenance_saved_components)
    await asyncio.wait_for(entered.wait(), 2)
    assert app.state.tgbot_task is not first and len(generations) == 2
    await main._park_runtime(app)
    assert generations[-1].cancelled()


@pytest.mark.parametrize("invalid", [False, True])
async def test_disabled_or_invalid_configuration_never_constructs_http_client(monkeypatch, invalid):
    def configuration(_):
        if invalid:
            raise ValueError("invalid configuration")
        return None

    def client(_):
        pytest.fail("disabled transport constructed an HTTP client")

    monkeypatch.setattr(delivery, "configured", configuration)
    monkeypatch.setattr(delivery, "TelegramClient", client)
    await delivery.worker()


async def test_configuration_change_closes_client_without_admission(monkeypatch):
    config = SimpleNamespace(token="synthetic")
    settings = iter([config, None])
    client = SimpleNamespace(aclose=AsyncMock())
    admitted = AsyncMock()
    monkeypatch.setattr(delivery, "configured", lambda _: next(settings))
    monkeypatch.setattr(delivery, "TelegramClient", lambda _: client)
    monkeypatch.setattr(delivery, "deliver_once", admitted)
    await delivery.worker()
    client.aclose.assert_awaited_once()
    admitted.assert_not_awaited()


async def test_admission_failure_does_not_kill_worker_and_cancellation_closes_client(monkeypatch):
    config = SimpleNamespace(token="synthetic")
    entered = asyncio.Event()
    client = SimpleNamespace(aclose=AsyncMock())
    calls = 0

    async def admitted(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic unavailable database")
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(delivery, "configured", lambda _: config)
    monkeypatch.setattr(delivery, "TelegramClient", lambda _: client)
    monkeypatch.setattr(delivery, "deliver_once", admitted)
    task = asyncio.create_task(delivery.worker())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 2
    client.aclose.assert_awaited_once()
