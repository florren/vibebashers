"""T-041: прерванный узел восстанавливается из настоящего PostgreSQL checkpoint."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest

from app.agent import graph
from app.agent.checkpoints import TransactionalSaver
from app.agent.runner import AgentService
from app.agent.state import new_state
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.sim import baseline, run_lifecycle, runs
from app.sim.engine import Simulator

pytestmark = pytest.mark.integration


async def test_effect_and_checkpoint_are_atomic_on_crash(seeded, conn, monkeypatch):
    rid = conn.execute("select current_run_id from sim_state where id=1").fetchone()[0]
    calls = []

    async def ingest(state, deps):
        calls.append("ingest")
        await deps.ctx.conn.execute(
            "insert into settings(key,value) values('durable-effect','1') "
            "on conflict(key) do update set value=to_jsonb((settings.value::text)::int+1)"
        )
        state["current_node"] = "close"
        return state

    async def close(state, deps):
        return state

    monkeypatch.setattr(graph, "NODES", {"ingest": ingest, "close": close})
    monkeypatch.setattr(graph, "_finish", AsyncMock())
    original = TransactionalSaver.aput
    crash = True

    async def save(self, config, checkpoint, metadata, new_versions):
        nonlocal crash
        if crash and checkpoint["channel_values"].get("current_node") == "close":
            crash = False
            raise asyncio.CancelledError("прерывание между эффектом и durable checkpoint")
        return await original(self, config, checkpoint, metadata, new_versions)

    monkeypatch.setattr(TransactionalSaver, "aput", save)
    state = new_state(rid, {"id": 1}, 1, "test")
    async with await psycopg.AsyncConnection.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as ac:
        deps = SimpleNamespace(ctx=SimpleNamespace(conn=ac, dry_run=False), begin_step=AsyncMock())
        with pytest.raises(asyncio.CancelledError):
            await graph.run_graph(state, deps, ac)
        assert conn.execute("select value from settings where key='durable-effect'").fetchone() is None
        restored = await graph.run_graph(state, deps, ac, recover=True)
    assert restored["current_node"] == "close"
    assert calls == ["ingest", "ingest"]
    assert conn.execute("select value from settings where key='durable-effect'").fetchone()[0] == 1
    assert conn.execute("select count(*) from langgraph.checkpoints where run_id=%s", (rid,)).fetchone()[0] >= 2


async def test_node_guard_error_finishes_without_entering_close(seeded, conn, monkeypatch):
    rid = conn.execute("select current_run_id from sim_state where id=1").fetchone()[0]
    calls = []

    async def guarded_act(state, deps):
        calls.append("act")
        raise ValueError("stale_refund_scope")

    async def close(state, deps):
        calls.append("close")
        raise AssertionError("после ошибки guard побочные эффекты недопустимы")

    monkeypatch.setattr(graph, "NODES", {"act": guarded_act, "close": close})
    finish = AsyncMock()
    monkeypatch.setattr(graph, "_finish", finish)
    state = new_state(rid, {"id": 1}, 1, "test")
    state["current_node"] = "act"
    async with await psycopg.AsyncConnection.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as ac:
        deps = SimpleNamespace(
            ctx=SimpleNamespace(conn=ac, dry_run=False), begin_step=AsyncMock(), record_step=AsyncMock()
        )
        result = await graph.run_graph(state, deps, ac)
    assert calls == ["act"]
    assert result["outcome"] == "failed"
    finish.assert_awaited_once()
    assert finish.await_args.args[-2] == "failed"


async def test_real_agent_continues_same_run_without_repeating_refund(seeded, conn, monkeypatch):
    cid, amount, fee = conn.execute(
        "select o.client_id,o.amount_rub,o.fee_amount from operations o join clients c on c.id=o.client_id "
        "where o.error_code='PROC-QR-FEE-CHARGED' and c.segment_code='mass' and o.fee_amount>0 "
        "order by o.started_sim desc limit 1"
    ).fetchone()
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1")
    chain = ProviderChain([MockProvider()])
    close = graph.NODES["close"]
    interrupted = False
    entered = asyncio.Event()

    async def interrupt_close(state, deps):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            entered.set()
            await asyncio.Event().wait()
        return await close(state, deps)

    monkeypatch.setitem(graph.NODES, "close", interrupt_close)
    async with await psycopg.AsyncConnection.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as ac:
        received = await create_signal(
            ac,
            from_api_signal(
                {
                    "channel_code": "chat",
                    "client_id": cid,
                    "text": f"Оплатил по QR {amount} рублей, списали комиссию {fee} руб. СБП бесплатно, верните комиссию.",
                }
            ),
            source_code="api",
            emit_event=False,
        )
        await ac.commit()
        sid = received["signal_id"]
        task = asyncio.create_task(graph.process_signal(ac, signal_id=sid, chain=chain, profile=profile))
        await asyncio.wait_for(entered.wait(), timeout=30)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    arid, rid, outcome = conn.execute(
        "select id,sim_run_id,outcome from agent_runs where signal_id=%s", (sid,)
    ).fetchone()
    assert outcome is None
    before = conn.execute("select count(*) from ledger_entries where kind='refund'").fetchone()[0]
    assert before == 1
    now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    async with await psycopg.AsyncConnection.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as ac:
        recovered = await graph.recover_agent_run(ac, agent_run_id=arid, chain=chain, profile=profile, sim_time=now)
        assert recovered["outcome"] == "completed"
        assert await graph.recover_agent_run(ac, agent_run_id=arid, chain=chain, profile=profile, sim_time=now) is None
    assert conn.execute("select count(*) from ledger_entries where kind='refund'").fetchone()[0] == before
    assert conn.execute("select count(*) from agent_runs where signal_id=%s", (sid,)).fetchone()[0] == 1
    assert (
        conn.execute("select count(*) from agent_steps where run_id=%s and node='normalize'", (arid,)).fetchone()[0]
        == 1
    )
    totals = conn.execute(
        "select ar.total_tokens,(select sum(prompt_tokens+completion_tokens) from agent_steps where run_id=ar.id) "
        "from agent_runs ar where id=%s",
        (arid,),
    ).fetchone()
    assert totals[0] == totals[1] and totals[0] > 0


async def test_resume_rejects_terminal_and_preserves_sim_time_rng(seeded, conn, monkeypatch):
    sim = Simulator(dsn=seeded)
    await sim.load_state()
    monkeypatch.setattr(sim, "_start_loop", lambda: setattr(sim.clock, "running", True))
    await sim.control("start", label="recovery")
    await sim.control("pause")
    before = conn.execute("select sim_time,rng_state from sim_state where id=1").fetchone()
    await sim.control("resume")
    after = conn.execute("select sim_time,rng_state from sim_state where id=1").fetchone()
    assert after == before
    assert conn.execute("select resumed_count from sim_runs where id=%s", (sim.run_id,)).fetchone()[0] == 1
    await sim.control("stop")
    with pytest.raises(ValueError, match="paused/interrupted"):
        await sim.control("resume")
    await sim.shutdown()


async def test_missing_legacy_checkpoint_refuses_resume_before_effects(seeded, conn):
    sim = Simulator(dsn=seeded)
    await sim.load_state()
    async with await psycopg.AsyncConnection.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as ac:
        rid = await runs.create_run(ac, kind="free", label="legacy", seed=42, sim_time=sim.clock.sim_time)
        received = await create_signal(
            ac,
            from_api_signal({"channel_code": "chat", "text": "Тест восстановления"}),
            source_code="api",
            emit_event=False,
            run_id=rid,
        )
        await ac.execute(
            "insert into agent_runs(kind,sim_run_id,signal_id,prompt_version,thread_id) values('agent',%s,%s,'v1',%s)",
            (rid, received["signal_id"], f"{rid}:{received['signal_id']}"),
        )
        await runs.set_run_status(ac, rid, "paused")
        await ac.commit()
    await sim.load_state()
    service = AgentService(
        ProviderChain([MockProvider()]), LLMProfile(code="mock", provider="mock", model="mock-1"), dsn=seeded
    )
    sim.before_resume = service.validate_recovery
    before = conn.execute("select sim_time,rng_state,running from sim_state where id=1").fetchone()
    with pytest.raises(ValueError, match="durable checkpoint"):
        await sim.control("resume")
    assert conn.execute("select sim_time,rng_state,running from sim_state where id=1").fetchone() == before
    assert conn.execute("select status,resumed_count from sim_runs where id=%s", (rid,)).fetchone() == ("paused", 0)
    await sim.shutdown()


@pytest.mark.parametrize("action", ["archive", "delete"])
async def test_checkpoint_ownership_isolated_during_purge(seeded, conn, tmp_path, monkeypatch, action):
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    ids = [
        conn.execute(
            "insert into sim_runs(kind,label,seed,status,started_sim,finished_at) "
            "values('free','checkpoint ownership',42,'completed',now(),now()) returning id"
        ).fetchone()[0]
        for _ in range(2)
    ]
    for rid in ids:
        thread = f"{rid}:1"
        conn.execute(
            "insert into langgraph.checkpoints(thread_id,checkpoint_id,checkpoint) values(%s,'test','{}')", (thread,)
        )
        conn.execute(
            "insert into langgraph.checkpoint_blobs(thread_id,channel,version,type,blob) values(%s,'state','1','json','{}')",
            (thread,),
        )
        conn.execute(
            "insert into langgraph.checkpoint_writes(thread_id,checkpoint_id,task_id,idx,channel,blob) values(%s,'test','test',0,'state','{}')",
            (thread,),
        )
    async with await psycopg.AsyncConnection.connect(
        seeded.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as ac:
        await getattr(run_lifecycle, action)(ac, ids[0])
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        assert conn.execute(f"select run_id from langgraph.{table}").fetchall() == [(ids[1],)]
    assert conn.execute("select count(*) from langgraph.checkpoint_migrations").fetchone()[0] == 10
