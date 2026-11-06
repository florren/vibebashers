"""Независимые PG-соединения сериализуют normal entry до эффектов графа/provider."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from app.agent import graph
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider

pytestmark = pytest.mark.integration
PROFILE = LLMProfile(code="mock", provider="mock", model="mock-1", role="main")


async def _signal(dsn: str, *, emit: bool = False) -> int:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        row = await create_signal(
            conn,
            from_api_signal({"channel_code": "email", "text": "Не могу открыть вклад в приложении."}),
            source_code="api",
            emit_event=emit,
        )
        assert row["status"] == "accepted"
        await conn.commit()
        return int(row["signal_id"])


@pytest.mark.parametrize("autocommit", [False, True])
@pytest.mark.parametrize("modes", [(False, False), (False, True), (True, False), (True, True)])
async def test_normal_entry_claim_serializes_independent_connections(
    seeded: str, monkeypatch: Any, autocommit: bool, modes: tuple[bool, bool]
) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    sid = await _signal(dsn)
    async with await psycopg.AsyncConnection.connect(dsn) as setup:
        run_id = await _running(setup)
    prepared, release, second_prepared = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_profiles = graph.run_profiles
    calls = 0
    effects: list[int] = []

    async def profiles(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            prepared.set()
            await release.wait()
        else:
            second_prepared.set()
        return await real_profiles(*args, **kwargs)

    async def notify(*args: Any, **kwargs: Any) -> None:
        pass

    async def deps(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(ctx=SimpleNamespace(notify=notify))

    async def run(state: Any, deps: Any, conn: Any) -> Any:
        effects.append(state["agent_run_id"])
        return state

    monkeypatch.setattr(graph, "run_profiles", profiles)
    monkeypatch.setattr(graph, "load_deps", deps)
    monkeypatch.setattr(graph, "run_graph", run)
    async with (
        await psycopg.AsyncConnection.connect(dsn, autocommit=autocommit) as one,
        await psycopg.AsyncConnection.connect(dsn, autocommit=autocommit) as two,
    ):
        tasks = [
            asyncio.create_task(
                graph.process_signal(
                    one,
                    signal_id=sid,
                    chain=ProviderChain([MockProvider()]),
                    profile=PROFILE,
                    new_only=modes[0],
                    current_run_id=run_id,
                    entry_allowed=lambda: True,
                )
            )
        ]
        try:
            await asyncio.wait_for(prepared.wait(), 3)
            tasks.append(
                asyncio.create_task(
                    graph.process_signal(
                        two,
                        signal_id=sid,
                        chain=ProviderChain([MockProvider()]),
                        profile=PROFILE,
                        new_only=modes[1],
                        current_run_id=run_id,
                        entry_allowed=lambda: True,
                    )
                )
            )
            # Наблюдаем конкурирующий старый вход либо реальное ожидание rowlock.
            async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as observer:
                for _ in range(200):
                    row = await (
                        await observer.execute(
                            "select wait_event_type from pg_stat_activity where pid=%s", (two.info.backend_pid,)
                        )
                    ).fetchone()
                    if second_prepared.is_set() or (row and row[0] == "Lock"):
                        break
                    await asyncio.sleep(0.005)
                else:
                    pytest.fail("second entry neither competed nor reached its database claim")
            assert not second_prepared.is_set(), "two entries passed duplicate lookup before either AR committed"
        finally:
            release.set()
            await asyncio.gather(*tasks)
        assert len(effects) == 1
        assert await (await one.execute("select count(*) from agent_runs where signal_id=%s", (sid,))).fetchone() == (
            1,
        )


def _stub_graph(monkeypatch: Any, effects: list[int], dsn: str, *, check_free: bool = False) -> None:
    async def notify(*args: Any, **kwargs: Any) -> None:
        pass

    async def deps(*args: Any, **kwargs: Any) -> Any:
        if check_free:
            async with await psycopg.AsyncConnection.connect(dsn) as other:
                await other.execute(
                    "select id from signals where id=(select signal_id from agent_runs where id=%s) for update nowait",
                    (kwargs["agent_run_id"],),
                )
        return SimpleNamespace(ctx=SimpleNamespace(notify=notify))

    async def run(state: Any, deps: Any, conn: Any) -> Any:
        if check_free:
            async with await psycopg.AsyncConnection.connect(dsn) as other:
                await other.execute("select id from signals where id=%s for update nowait", (state["signal"]["id"],))
        effects.append(state["agent_run_id"])
        return state

    monkeypatch.setattr(graph, "load_deps", deps)
    monkeypatch.setattr(graph, "run_graph", run)


async def _running(conn: Any) -> int:
    row = await (await conn.execute("select current_run_id from sim_state where id=1")).fetchone()
    run_id = int(row[0])
    await conn.execute("update sim_state set running=true where id=1")
    await conn.execute("update sim_runs set status='running' where id=%s", (run_id,))
    await conn.commit()
    return run_id


async def test_claim_is_released_before_graph_provider_work(seeded: str, monkeypatch: Any) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    sid = await _signal(dsn)
    effects: list[int] = []
    _stub_graph(monkeypatch, effects, dsn, check_free=True)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        result = await graph.process_signal(conn, signal_id=sid, chain=ProviderChain([MockProvider()]), profile=PROFILE)
    assert result is not None and len(effects) == 1


@pytest.mark.parametrize("outcome", ["failed", "awaiting_human", None])
async def test_catchup_skips_any_previous_ar_but_manual_failed_retry_remains(
    seeded: str, monkeypatch: Any, outcome: str | None
) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    sid = await _signal(dsn)
    effects: list[int] = []
    _stub_graph(monkeypatch, effects, dsn)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        run_id = await _running(conn)
        first = await graph.process_signal(conn, signal_id=sid, chain=ProviderChain([MockProvider()]), profile=PROFILE)
        await conn.execute(
            "update agent_runs set outcome=%s,error='synthetic network/unknown admission' where id=%s",
            (outcome, first["agent_run_id"]),
        )
        await conn.commit()
        assert (
            await graph.process_signal(
                conn,
                signal_id=sid,
                chain=ProviderChain([MockProvider()]),
                profile=PROFILE,
                new_only=True,
                current_run_id=run_id,
                entry_allowed=lambda: True,
            )
            is None
        )
        assert len(effects) == 1
        if outcome == "failed":
            assert (
                await graph.process_signal(conn, signal_id=sid, chain=ProviderChain([MockProvider()]), profile=PROFILE)
                is not None
            )
            assert len(effects) == 2


@pytest.mark.parametrize("guard", ["local_pause", "db_pause", "foreign_run", "changed_owner"])
async def test_catchup_owner_and_pause_guards_are_read_only(seeded: str, monkeypatch: Any, guard: str) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    sid = await _signal(dsn)
    effects: list[int] = []
    _stub_graph(monkeypatch, effects, dsn)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        run_id = await _running(conn)
        if guard == "db_pause":
            await conn.execute("update sim_state set running=false where id=1")
            await conn.commit()
        if guard == "foreign_run":
            run_id += 10000
        calls = 0

        def allowed() -> bool:
            nonlocal calls
            calls += 1
            return guard != "local_pause" and (guard != "changed_owner" or calls == 1)

        assert (
            await graph.process_signal(
                conn,
                signal_id=sid,
                chain=ProviderChain([MockProvider()]),
                profile=PROFILE,
                new_only=True,
                current_run_id=run_id,
                entry_allowed=allowed,
            )
            is None
        )
        assert not effects
        assert await (await conn.execute("select count(*) from agent_runs where signal_id=%s", (sid,))).fetchone() == (
            0,
        )


async def test_skip_releases_savepoint_lock_without_committing_caller_work(seeded: str, monkeypatch: Any) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    sid = await _signal(dsn)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("insert into settings(key,value) values('entry_claim_caller_probe','true')")
        assert (
            await graph.process_signal(
                conn,
                signal_id=sid,
                chain=ProviderChain([MockProvider()]),
                profile=PROFILE,
                new_only=True,
                current_run_id=1,
                entry_allowed=lambda: False,
            )
            is None
        )
        async with await psycopg.AsyncConnection.connect(dsn) as other:
            await other.execute("select id from signals where id=%s for update nowait", (sid,))
            assert await (
                await other.execute("select count(*) from settings where key='entry_claim_caller_probe'")
            ).fetchone() == (0,)
        assert await (
            await conn.execute("select count(*) from settings where key='entry_claim_caller_probe'")
        ).fetchone() == (1,)
        await conn.rollback()


async def test_native_disconnect_lost_notify_is_claimed_once_after_reconnect(seeded: str, monkeypatch: Any) -> None:
    from app.agent.runner import AgentService

    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        run_id = await _running(conn)
    service = AgentService(
        ProviderChain([MockProvider()]),
        PROFILE,
        dsn=dsn,
        sim=SimpleNamespace(run_id=run_id, clock=SimpleNamespace(running=True)),
    )
    service._recover_on_start = False
    effects: list[int] = []
    _stub_graph(monkeypatch, effects, dsn)
    finished = asyncio.Event()
    native_run = graph.run_graph

    async def run(*args: Any, **kwargs: Any) -> Any:
        result = await native_run(*args, **kwargs)
        finished.set()
        return result

    monkeypatch.setattr(graph, "run_graph", run)
    native_connect = psycopg.AsyncConnection.connect
    listening = 0
    signal_ids: list[int] = []

    class DisconnectOnce:
        def __init__(self, conn: Any):
            self.conn = conn

        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            return await self.conn.execute(*args, **kwargs)

        async def close(self) -> None:
            await self.conn.close()

        async def notifies(self, **kwargs: Any) -> Any:
            await self.conn.close()
            # Commit/NOTIFY происходит без LISTEN owner; во второй сессии его уже нет.
            signal_ids.append(await _signal(dsn, emit=True))
            raise psycopg.OperationalError("synthetic listener disconnected")
            yield None

    async def connect(*args: Any, **kwargs: Any) -> Any:
        nonlocal listening
        conn = await native_connect(*args, **kwargs)
        if kwargs.get("autocommit") is True:
            listening += 1
            if listening == 1:
                return DisconnectOnce(conn)
        return conn

    monkeypatch.setattr("app.agent.runner.psycopg.AsyncConnection.connect", connect)
    service._task = asyncio.create_task(service._loop())
    try:
        await asyncio.wait_for(finished.wait(), 10)
        await asyncio.gather(*list(service._inflight))
        await service._catch_up_new()
        await service._catch_up_new()
        assert listening == 2 and len(effects) == 1 and service.processed == 1
        async with await native_connect(dsn) as conn:
            assert await (
                await conn.execute("select count(*) from agent_runs where signal_id=%s", (signal_ids[0],))
            ).fetchone() == (1,)
    finally:
        await service.stop()
