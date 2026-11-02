"""Один incident: блокировка parent до FK INSERT исключает lock upgrade cycle."""

import asyncio
import json

import psycopg
import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.write import link_signal_to_incident
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import dsn

from .test_proactive_recovery import prepare


@pytest.mark.asyncio
async def test_same_incident_links_lock_parent_before_foreign_key_insert(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, state, _ = await prepare(conn)
        incident = (await (await conn.execute("select id from incidents where run_id=%s", (run,))).fetchone())[0]
        inputs = []
        for index in range(2):
            msg = from_api_signal(
                {"client_id": people[0], "channel_code": "chat", "text": "Не приходит смс-код для перевода."}
            )
            msg["external_id"] = f"T039-links-{run}-{index}"
            result = await create_signal(conn, msg, source_code="api", run_id=run, sim_time=at)
            agent = (
                await (
                    await conn.execute(
                        "insert into agent_runs(sim_run_id,signal_id,prompt_version,started_sim) values(%s,%s,'test',%s) returning id",
                        (run, result["signal_id"], at),
                    )
                ).fetchone()
            )[0]
            inputs.append((result["signal_id"], agent))
        await conn.commit()
        entered, release, second_insert = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Connection:
            def __init__(self, connection, first):
                self.connection, self.first = connection, first

            def __getattr__(self, name):
                return getattr(self.connection, name)

            async def execute(self, query, *args, **kwargs):
                is_link = isinstance(query, str) and query.startswith("insert into incident_signals")
                if is_link and not self.first:
                    second_insert.set()
                cursor = await self.connection.execute(query, *args, **kwargs)
                if is_link and self.first:
                    entered.set()
                    await release.wait()
                return cursor

        async with (
            await psycopg.AsyncConnection.connect(dsn(seeded)) as one,
            await psycopg.AsyncConnection.connect(dsn(seeded)) as two,
        ):
            first_pid, second_pid = one.info.backend_pid, two.info.backend_pid

            async def link(connection, pair, first):
                ctx = ToolContext(Connection(connection, first), run_id=run, agent_run_id=pair[1], sim_time=at)
                await link_signal_to_incident(ctx, pair[0], incident)
                # Существующий следующий gift/resume guard использует полный
                # row lock в этой же act TX; сам подарок здесь не создаётся.
                await connection.execute("select id from incidents where id=%s for update", (incident,))
                await connection.commit()

            first = asyncio.create_task(link(one, inputs[0], True))
            await entered.wait()
            second = asyncio.create_task(link(two, inputs[1], False))
            try:
                async with asyncio.timeout(5):
                    while True:
                        blockers = (
                            await (await conn.execute("select pg_blocking_pids(%s)", (second_pid,))).fetchone()
                        )[0]
                        if first_pid in blockers:
                            break
                assert not second_insert.is_set(), "parent lock должен предшествовать FK INSERT второго linker"
            finally:
                release.set()
                await asyncio.gather(first, second)
        assert await (
            await conn.execute(
                "select count(*) from incident_signals where incident_id=%s and signal_id=any(%s)",
                (incident, [row[0] for row in inputs]),
            )
        ).fetchone() == (2,)
        assert await (
            await conn.execute(
                "select i.mass_impact,e.affected_count from incidents i join incident_economics e on e.incident_id=i.id where i.id=%s",
                (incident,),
            )
        ).fetchone() == (1, 1)


@pytest.mark.asyncio
async def test_actual_human_refund_route_audit_remains_compatible_with_linker_lock(seeded, monkeypatch):
    import uuid
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from app.abs import service as abs_service
    from app.api import abs as abs_api
    from app.sim.behavior.runtime import refresh_effect_time

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, state, _ = await prepare(conn)
        incident = (await (await conn.execute("select id from incidents where run_id=%s", (run,))).fetchone())[0]
        op = (
            await (
                await conn.execute(
                    "insert into operations(run_id,client_id,product_code,op_type,method,system_path,status,error_code,amount_rub,fee_amount,started_sim) "
                    "values(%s,%s,'debit_card','card_payment','qr_sbp',ARRAY['processing'],'success','PROC-QR-FEE-CHARGED',100,10,%s) returning id",
                    (run, people[0], at),
                )
            ).fetchone()
        )[0]
        await abs_service.ensure_operation_posted(conn, op)
        account, before_balance = await (
            await conn.execute(
                "select id,balance from accounts where client_id=%s and status='active' order by id limit 1",
                (people[0],),
            )
        ).fetchone()
        await conn.commit()
        human_holds_account, release_human = asyncio.Event(), asyncio.Event()
        history_written, agent_linked = asyncio.Event(), asyncio.Event()

        class HumanConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            async def execute(self, query, *args, **kwargs):
                cursor = await self.connection.execute(query, *args, **kwargs)
                if isinstance(query, str) and query.startswith("update accounts set balance"):
                    human_holds_account.set()
                    await release_human.wait()
                if isinstance(query, str) and query.startswith("insert into incident_status_history"):
                    history_written.set()
                return cursor

        @asynccontextmanager
        async def human_db():
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as raw:
                yield HumanConnection(raw)
                await raw.commit()

        async def context(_request, _connection):
            return run, at

        monkeypatch.setattr(abs_api, "db", human_db)
        monkeypatch.setattr(abs_api, "run_context", context)
        batch = abs_api.RefundBatch(
            items=[abs_api.RefundItem(operation_id=op, amount_rub=10, correlation_id=uuid.uuid4())],
            reason="synthetic concurrency proof",
            incident_id=incident,
        )
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as agent_connection:
            agent_pid = agent_connection.info.backend_pid

            async def agent():
                ctx = ToolContext(
                    agent_connection,
                    run_id=run,
                    agent_run_id=state["agent_run_id"],
                    sim_time=at,
                    effect_time_fence=refresh_effect_time,
                )
                await link_signal_to_incident(ctx, sid, incident)
                agent_linked.set()
                await agent_connection.execute("select id from accounts where id=%s for update", (account,))
                await agent_connection.execute("select id from incidents where id=%s for update", (incident,))
                await agent_connection.commit()

            human_task = asyncio.create_task(abs_api.post_abs_refunds(SimpleNamespace(), batch))
            await human_holds_account.wait()
            agent_task = asyncio.create_task(agent())
            try:
                async with asyncio.timeout(5):
                    await agent_linked.wait()
                    while not (
                        await (
                            await conn.execute("select cardinality(pg_blocking_pids(%s))>0", (agent_pid,))
                        ).fetchone()
                    )[0]:
                        pass  # I/O await наблюдает фактическую блокировку, без sleep/race delay.
                    release_human.set()
                    response = await human_task
                    await agent_task
                assert response.status_code == 202 and history_written.is_set()
                assert json.loads(response.body)["accepted"] == 1
            finally:
                release_human.set()
                for task in (agent_task, human_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(agent_task, human_task, return_exceptions=True)
        assert (await (await conn.execute("select balance from accounts where id=%s", (account,))).fetchone())[
            0
        ] == before_balance + 10
        duplicate = await abs_api.post_abs_refunds(SimpleNamespace(), batch)
        duplicate_body = json.loads(duplicate.body)
        assert duplicate_body["accepted"] == 0 and duplicate_body["skipped_duplicates"] == 1
        assert (
            await (
                await conn.execute("select count(*) from ledger_entries where operation_id=%s and kind='refund'", (op,))
            ).fetchone()
        ) == (1,)
        assert (
            await (
                await conn.execute(
                    "select count(*) from incident_status_history where incident_id=%s and actor_type='human'",
                    (incident,),
                )
            ).fetchone()
        ) == (1,)
