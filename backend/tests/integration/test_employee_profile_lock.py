"""Snapshot сотрудника не блокирует LLM accounting и управление обычным банком."""

import asyncio

import psycopg
import pytest

from app.agent.graph import process_signal
from app.config import get_settings
from app.demo import execution
from app.demo.settings import save
from app.llm import credentials
from app.sim import scenarios
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_full_simulation_controls import app_for

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mode", ["simulation", "demo"])
async def test_employee_releases_profile_lock_before_llm_and_hitl(seeded, monkeypatch, mode):
    app, _ = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    await sim.control("start", label="employee profile lock")
    rid = sim.run_id
    entered, release = asyncio.Event(), asyncio.Event()
    task = None

    async def respond(*args, **kwargs):
        # Настоящее второе соединение, как у LLM accounting/продолжения HITL.
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as probe:
            acquired = await (
                await probe.execute("select pg_try_advisory_xact_lock(%s)", (credentials.LOCK,))
            ).fetchone()
            assert acquired == (True,), "snapshot сотрудника удерживает credentials.LOCK"
        entered.set()
        await release.wait()
        return {"body": "Согласовано", "decision": "accept"}, {"source": "mock", "model": "mock"}

    monkeypatch.setattr(execution, "respond", respond)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await save(conn, rid, {"mode": mode, "enabled": True, "status": "running", "emulate_humans": True})
            item = (
                await scenarios.inject(
                    conn,
                    {
                        "id": "deposit_promo_rate",
                        "inject": [
                            {
                                "channel": "chat",
                                "client": {"segment": "ultra_vip"},
                                "text": "Не могу открыть вклад, приложение зависло с ошибкой 503. Прошу решить проблему.",
                            }
                        ],
                    },
                    rid,
                    sim_time=sim.clock.sim_time,
                )
            )[0]
            await conn.commit()
            state = await process_signal(conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
            assert state["outcome"] == "awaiting_human"
            task = asyncio.create_task(execution.employees(app, conn, rid, sim.clock.sim_time))
            # Ошибка probe должна дойти до теста, а не маскироваться timeout.
            ready = asyncio.create_task(entered.wait())
            try:
                await asyncio.wait_for(asyncio.wait({ready, task}, return_when=asyncio.FIRST_COMPLETED), 5)
                if task.done():
                    await task
                assert entered.is_set()
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)
            # Медленный ответ сотрудника не занимает lock симулятора.
            before = sim.clock.sim_time
            await asyncio.wait_for(sim.step(1), 5)
            assert sim.clock.sim_time > before
            release.set()
            assert await asyncio.wait_for(task, 10) is True
            assert (
                await (
                    await conn.execute(
                        "select decision from human_decisions where signal_id=%s order by id limit 1",
                        (item["signal_id"],),
                    )
                ).fetchone()
            ) == ("accept",)
        await asyncio.wait_for(sim.control("pause"), 5)
        await asyncio.wait_for(sim.control("resume"), 5)
        await asyncio.wait_for(sim.control("stop"), 5)
        assert not sim.clock.running and sim.run_status == "stopped"
    finally:
        release.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
