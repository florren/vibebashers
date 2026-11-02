"""T-161: inactive sink, SHARE/status races и stale Simulator на настоящем PG16."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest

from app.agent.tools.base import ClientStateIntent, ToolContext
from app.agent.tools.write import set_client_state
from app.sim import runs
from app.sim.behavior import runtime
from app.sim.behavior.store import record_agent_state_intent
from tests.helpers import dsn, new_run

from .test_behavior_runtime import setup


async def case(conn, monkeypatch, url, *, client_override=None):
    run, client, now, sim = await setup(conn, monkeypatch, url)
    await sim.conn.close()
    if client_override is not None:
        client = client_override
    signal = (
        await (
            await conn.execute(
                "insert into signals(run_id,client_id,channel_code,text,received_sim,origin) values(%s,%s,'chat','Проверка настоящего контекста',%s,'jury') returning id",
                (run, client, now),
            )
        ).fetchone()
    )[0]
    agent = (
        await (
            await conn.execute(
                "insert into agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) values('agent',%s,%s,%s,%s,'inactive-native-case') returning id",
                (run, signal, client, now),
            )
        ).fetchone()
    )[0]
    await conn.commit()
    return run, client, now, signal, agent


async def unchanged(conn, run, client):
    return await (
        await conn.execute(
            "select (select jsonb_build_array(sim_time,day_no,rng_state,current_run_id) from sim_state where id=1),"
            "(select coalesce(jsonb_agg(to_jsonb(s) order by id),'[]') from client_states s where run_id=%s),"
            "(select churn_risk from clients where id=%s)",
            (run, client),
        )
    ).fetchone()


async def counts(conn, run):
    return await (
        await conn.execute(
            "select (select count(*) from behavior_agent_intents where run_id=%s),"
            "(select count(*) from behavior_evidence where run_id=%s),"
            "(select count(*) from behavior_runtime where run_id=%s),"
            "(select count(*) from client_states where run_id=%s)",
            (run,) * 4,
        )
    ).fetchone()


async def wait_lock(observer, pid):
    async def wait():
        while True:
            await observer.execute("select pg_stat_clear_snapshot()")
            row = await (
                await observer.execute("select wait_event_type from pg_stat_activity where pid=%s", (pid,))
            ).fetchone()
            if row == ("Lock",):
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("switch", [False, True])
async def test_inactive_sink_never_falls_back_to_legacy_or_initializes_marker(seeded, monkeypatch, legacy, switch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, signal, agent = await case(conn, monkeypatch, seeded)
        if legacy:
            await conn.execute("delete from behavior_runs where run_id=%s", (run,))
        if switch:
            await new_run(conn, "active other bank run")
        else:
            await runs.set_run_status(conn, run, "stopped", now)
        await conn.commit()
        before = await unchanged(conn, run, client)
        await runtime.require_run(conn, run)
        sink = await runtime.state_sink(conn, run)
        assert sink is record_agent_state_intent
        ctx = ToolContext(conn, run_id=run, agent_run_id=agent, sim_time=now, state_evidence_sink=sink)
        result = await set_client_state(ctx, client, "churned", "agent:historical", signal)
        assert result["accepted"] is False and result["status"] == "suppressed"
        assert result["reason"] == "inactive_run" and result["evidence_id"] is None
        assert await runtime.twin_sink(conn, run, 987654321) is True
        await conn.commit()
        assert await counts(conn, run) == (0, 0, 0, 0)
        assert await unchanged(conn, run, client) == before
        assert (
            await (await conn.execute("select count(*) from behavior_runs where run_id=%s", (run,))).fetchone()
        ) == (0 if legacy else 1,)


@pytest.mark.asyncio
@pytest.mark.parametrize("switch", [False, True])
async def test_share_pin_linearizes_accepted_intent_before_stop_or_current_switch(seeded, monkeypatch, switch):
    async with (
        await psycopg.AsyncConnection.connect(dsn(seeded)) as node,
        await psycopg.AsyncConnection.connect(dsn(seeded)) as controller,
    ):
        run, client, now, signal, agent = await case(node, monkeypatch, seeded)
        before = await unchanged(node, run, client)
        intent = ClientStateIntent(run, agent, client, "satisfied", "agent:bounded", now, signal, None)
        accepted = await record_agent_state_intent(node, intent)
        assert accepted.accepted is True and accepted.evidence_id > 0 and accepted.reason is None
        pid = (await (await controller.execute("select pg_backend_pid()")).fetchone())[0]
        await controller.commit()

        async def stop_or_switch():
            if switch:
                other = await runs.create_run(controller, kind="free", label="race new run", seed=1, sim_time=now)
                assert other != run
            else:
                await runs.set_run_status(controller, run, "stopped", now)
            await controller.commit()

        task = asyncio.create_task(stop_or_switch())
        try:
            await wait_lock(node, pid)
            assert not task.done()
            await node.commit()
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        current = await unchanged(node, run, client)
        assert current[0][:3] == before[0][:3] and current[1:] == before[1:]
        suppressed = await record_agent_state_intent(node, intent)
        assert not suppressed.accepted and suppressed.evidence_id is None and suppressed.reason == "inactive_run"
        await node.commit()
        assert await counts(node, run) == (1, 1, 0, 0)


@pytest.mark.asyncio
async def test_stale_simulator_cannot_overwrite_factory_pointer_clock_rng_or_create_run(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        _, _, _, stale = await setup(conn, monkeypatch, seeded)
        old_run = stale.run_id
        newer = await new_run(conn, "real other controller", kind="free")
        assert newer != old_run
        before = (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0]
        total = (await (await conn.execute("select count(*) from sim_runs")).fetchone())[0]
        await conn.rollback()
        stale.clock.sim_time += dt.timedelta(minutes=7)
        with pytest.raises(ValueError, match="устарел"):
            await stale.persist()
        memory = (stale.clock.sim_time, stale.clock.speed, stale.rng.dump_state(), dict(stale.stats))
        for action, options in [("set_speed", {"speed": 900}), ("start", {"label": "must not exist"})]:
            with pytest.raises(ValueError, match="устарел"):
                await stale.control(action, **options)
            assert (stale.clock.sim_time, stale.clock.speed, stale.rng.dump_state(), stale.stats) == memory
        with pytest.raises(ValueError, match="устарел"):
            await stale.step(1)
        assert (stale.clock.sim_time, stale.clock.speed, stale.rng.dump_state(), stale.stats) == memory
        assert (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0] == before
        assert (await (await conn.execute("select count(*) from sim_runs")).fetchone()) == (total,)
        await stale.conn.close()


@pytest.mark.asyncio
async def test_start_factory_and_rng_persist_rollback_together_then_retry(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        _, _, _, sim = await setup(conn, monkeypatch, seeded)
        world = await sim._ensure_world()
        await sim.conn.commit()
        original_rng = sim.rng
        before = (sim.run_id, sim.run_status, sim.seed, sim.rng.dump_state(), dict(sim.stats))
        state = (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0]
        total = (await (await conn.execute("select count(*) from sim_runs")).fetchone())[0]
        await conn.rollback()
        persist = sim.persist
        starts = []
        monkeypatch.setattr(sim, "_start_loop", lambda: starts.append(True))

        async def fail():
            raise ValueError("controlled stale before start commit")

        monkeypatch.setattr(sim, "persist", fail)
        with pytest.raises(ValueError, match="controlled stale"):
            await sim.control("start", label="atomic start", seed=17)
        assert (sim.run_id, sim.run_status, sim.seed, sim.rng.dump_state(), sim.stats) == before
        assert sim.rng is original_rng and sim.world is world and world.textgen.rnd is original_rng
        assert starts == []
        assert (await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone())[0] == state
        assert (await (await conn.execute("select count(*) from sim_runs")).fetchone()) == (total,)
        await conn.rollback()
        monkeypatch.setattr(sim, "persist", persist)
        await sim.control("start", label="atomic start", seed=17)
        assert starts == [True]
        native = await (
            await conn.execute("select current_run_id,rng_state,running from sim_state where id=1")
        ).fetchone()
        assert native == (sim.run_id, sim.rng.dump_state(), True)
        assert sim.run_id != before[0]
        await sim.conn.close()


@pytest.mark.asyncio
async def test_refund_then_enqueue_shares_run_with_tick_and_rolls_back_all_effects(seeded, monkeypatch):
    from app.abs import service as abs_svc
    from app.rules.engine import check_rules

    from .test_behavior_owner import POLICY

    async with (
        await psycopg.AsyncConnection.connect(dsn(seeded)) as node,
        await psycopg.AsyncConnection.connect(dsn(seeded)) as tick,
    ):
        # Как в штатном ABS invariant proof: seed balances требуют полного
        # backfill, а не только одной выбранной refund operation.
        await abs_svc.backfill_ledger(node)
        await node.commit()
        operation, client = await (
            await node.execute(
                "select id,client_id from operations where error_code='PROC-QR-FEE-CHARGED' and method='qr_sbp' and op_type='card_payment' and fee_amount>0 order by id limit 1"
            )
        ).fetchone()
        run, client, now, signal, agent = await case(node, monkeypatch, seeded, client_override=client)
        native = (
            await (await node.execute("select to_jsonb(o) from operations o where id=%s", (operation,))).fetchone()
        )[0]
        native["operation_id"] = operation
        matches = await check_rules(
            node, run_id=run, signal_id=signal, agent_run_id=agent, operations=[native], tariff_fee_pct=0
        )
        assert any(row["rule_code"] == "RULE-QR-FEE-001" for row in matches)
        await abs_svc.ensure_operation_posted(node, operation)
        account = await abs_svc.ensure_account(node, client)
        await node.commit()
        balance = (
            await (await node.execute("select balance from accounts where id=%s", (account["account_id"],))).fetchone()
        )[0]
        before = await unchanged(node, run, client)
        refund = await abs_svc.refund_fee(
            node,
            run_id=run,
            operation_id=operation,
            amount_rub=None,
            rule_id="RULE-QR-FEE-001",
            reason="native rule rollback proof",
            posted_sim=now,
            agent_run_id=agent,
        )
        assert refund["duplicate"] is False and refund["amount_rub"] > 0
        await tick.execute("select id from sim_state where id=1 for update")
        await runtime.prepare_run(tick, run, now, POLICY)
        pid = (await (await tick.execute("select pg_backend_pid()")).fetchone())[0]

        async def lock_account():
            return await (
                await tick.execute("select balance from accounts where id=%s for update", (account["account_id"],))
            ).fetchone()

        task = asyncio.create_task(lock_account())
        try:
            await wait_lock(node, pid)
            result = await asyncio.wait_for(
                record_agent_state_intent(
                    node, ClientStateIntent(run, agent, client, "satisfied", "agent:refund", now, signal, None)
                ),
                timeout=5,
            )
            assert result.accepted is True
            await node.rollback()  # Тот же graph TX: refund и запрос не переживают abort.
            assert await asyncio.wait_for(task, timeout=5) == (balance,)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await tick.rollback()
        assert await counts(node, run) == (0, 0, 0, 0)
        assert await unchanged(node, run, client) == before
        assert (
            await (await node.execute("select balance from accounts where id=%s", (account["account_id"],))).fetchone()
        ) == (balance,)
        assert (
            await (
                await node.execute("select count(*) from ledger_entries where id=%s", (refund["entry_id"],))
            ).fetchone()
        ) == (0,)
        assert await abs_svc.check_invariant(node) == []
