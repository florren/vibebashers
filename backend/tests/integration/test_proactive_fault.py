"""T-039: native causal scope и повторяемый служебный вход, без gold/live HTTP."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent import nodes, proactive
from app.agent.graph import process_signal
from app.agent.tools import write
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.sim.events import EventBus, dumps
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now


class WrongProductLineMock(MockProvider):
    async def complete_structured(self, *args, **kwargs):
        obj, usage, raw = await super().complete_structured(*args, **kwargs)
        if "signal_type" in obj:
            obj = {**obj, "product_line": "deposits", "product_line_confidence": 0.99}
            raw = dumps(obj)
        return obj, usage, raw


async def fault(conn, run, at, *, emit=True):
    fid = (
        await (
            await conn.execute(
                "insert into faults(run_id,system_code,error_code,started_sim) "
                "values(%s,'notification_gw','NOTIF-DELAY',%s) returning id",
                (run, at),
            )
        ).fetchone()
    )[0]
    if emit:
        await EventBus(conn).emit(
            run,
            "fault.started",
            {
                "fault_id": fid,
                "system": "notification_gw",
                "error_code": "NOTIF-DELAY",
                "started_sim": at.isoformat(),
                "impact_count": 0,
                "affected_clients": 0,
            },
            at,
        )
    return fid


async def operation(conn, run, fid, client, at, *, path="notification_gw", code="NOTIF-DELAY"):
    return (
        await (
            await conn.execute(
                "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) "
                "values(%s,%s,'debit_card','transfer',%s,'failed',%s,%s,%s) returning id",
                (run, client, [path], code, fid, at),
            )
        ).fetchone()
    )[0]


@pytest.mark.asyncio
async def test_native_fault_zero_then_actual_impact_creates_one_service_anchor(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 service anchor")
        at = await sim_now(conn)
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        fid = await fault(conn, run, at)
        assert await proactive.produce(conn) == []
        await operation(conn, run, fid, client, at + dt.timedelta(minutes=1))
        # Ни payload impact, ни будущая persisted operation не доказывают текущий impact.
        assert await proactive.produce(conn) == []
        later = at + dt.timedelta(minutes=1)
        await conn.execute("update sim_state set sim_time=%s where id=1", (later,))
        first = await proactive.produce(conn)
        assert len(first) == 1
        await operation(conn, run, fid, client, later)
        assert await proactive.produce(conn) == first
        scope = await proactive.fault_scope(conn, run, fid, later)
        assert scope["affected_count"] == 1
        anchor = await (
            await conn.execute(
                "select s.client_id,s.origin,s.channel_code,s.source_fault_id,s.received_sim,m.source_code,s.meta "
                "from signals s join ingest_messages m on m.signal_id=s.id where s.id=%s",
                (first[0],),
            )
        ).fetchone()
        assert anchor[:6] == (None, "proactive", "proactive", fid, later, "fault_monitor")
        assert "gold" not in anchor[6] and "generator_hint" not in anchor[6]
        service = {
            "id": first[0],
            "origin": "proactive",
            "channel": "proactive",
            "channel_subtype": "system_logs",
            "client_id": None,
            "source_fault_id": fid,
        }
        assert (await proactive.service_scope(conn, service, run))["as_of"] == later
        after = later + dt.timedelta(minutes=5)
        await conn.execute("update sim_state set sim_time=%s where id=1", (after,))
        assert (await proactive.service_scope(conn, service, run))["as_of"] == after
        # Native origin/shape недостаточны без записи именно внутреннего producer.
        await conn.execute("update ingest_messages set source_code='api' where signal_id=%s", (first[0],))
        assert await proactive.service_scope(conn, service, run) is None
        assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()) == (1,)


@pytest.mark.asyncio
async def test_native_fault_scope_rejects_cross_run_future_wrong_path_and_missing_event(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 scope")
        at = await sim_now(conn)
        clients = [r[0] for r in await (await conn.execute("select id from clients order by id limit 5")).fetchall()]
        fid = await fault(conn, run, at)
        await operation(conn, run, fid, clients[0], at)
        await operation(conn, run, fid, clients[1], at + dt.timedelta(seconds=1))
        await operation(conn, run, fid, clients[2], at, path="processing")
        await operation(conn, run, fid, clients[3], at, code="DEP-TIMEOUT-503")
        other = await new_run(conn, "T039 decoy")
        await operation(conn, other, fid, clients[4], at)
        scope = await proactive.fault_scope(conn, run, fid, at)
        assert [c["client_id"] for c in scope["clients"]] == [clients[0]]
        assert await proactive.fault_scope(conn, other, fid, at) is None
        no_event = await fault(conn, other, at, emit=False)
        await operation(conn, other, no_event, clients[0], at)
        assert await proactive.fault_scope(conn, other, no_event, at) is None
        await conn.execute("update sim_runs set status='completed' where id=%s", (other,))
        assert await proactive.produce(conn) == []


@pytest.mark.asyncio
async def test_one_native_service_uses_normal_graph_and_per_client_consented_fanout(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 normal graph")
        at = await sim_now(conn)
        clients = [r[0] for r in await (await conn.execute("select id from clients order by id limit 3")).fetchall()]
        fid = await fault(conn, run, at)
        for index, client in enumerate(clients):
            await operation(conn, run, fid, client, at)
            await conn.execute(
                "update clients set consents=jsonb_build_object('proactive',%s), "
                "contacts=contacts||jsonb_build_object('preferred','chat') where id=%s",
                (index < 2, client),
            )
        [sid] = await proactive.produce(conn)
        await conn.commit()
        state = await process_signal(
            conn,
            signal_id=sid,
            chain=ProviderChain([WrongProductLineMock()], offline_mode="mock"),
            profile=MOCK_PROFILE,
        )
        assert state is not None and state["client"] is None
        assert state["classification"]["signal_type"] == "tech_fault"
        assert state["classification"]["system"] == "notification_gw"
        assert state["decision"]["client_action"]["kind"] == "proactive_notice"
        assert state["context"]["proactive_report"]["statuses"] == {"sent": 2}
        notices = await (
            await conn.execute(
                "select client_id,template_code,status,sent_sim from notifications "
                "where run_id=%s and recipient_type='client' order by client_id",
                (run,),
            )
        ).fetchall()
        assert notices == [(client, "proactive_fault", "sent", at) for client in clients[:2]]
        incident = await (
            await conn.execute("select fault_id,mass_impact,primary_client_id from incidents where run_id=%s", (run,))
        ).fetchall()
        assert incident == [(fid, 3, None)]
        assert await (
            await conn.execute("select team_code,co_team_codes from incidents where run_id=%s", (run,))
        ).fetchone() == ("team_notifications", ["team_cx"])
        assert await (
            await conn.execute("select affected_count from incident_economics where run_id=%s", (run,))
        ).fetchone() == (3,)
        steps = await (
            await conn.execute("select node from agent_steps where run_id=%s order by seq", (state["agent_run_id"],))
        ).fetchall()
        assert {"normalize", "identify_client", "gather_context", "classify", "decide", "act"} <= {r[0] for r in steps}
        assert not await (await conn.execute("select 1 from tasks where run_id=%s and kind='gift'", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved", [False, True])
async def test_delayed_service_rechecks_native_clock_and_fault_after_model(seeded, monkeypatch, resolved):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 delayed model")
        at = await sim_now(conn)
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        fid = await fault(conn, run, at)
        await operation(conn, run, fid, client, at)
        await conn.execute(
            "update clients set consents=jsonb_build_object('proactive',true), "
            "contacts=contacts||jsonb_build_object('preferred','chat') where id=%s",
            (client,),
        )
        [sid] = await proactive.produce(conn)
        await conn.commit()
        original = nodes._llm
        later = at + dt.timedelta(minutes=5)
        moved = False

        async def after_model(deps, node, *args, **kwargs):
            nonlocal moved
            answer = await original(deps, node, *args, **kwargs)
            if node == "decide":
                async with await psycopg.AsyncConnection.connect(dsn(seeded)) as other:
                    await other.execute("update sim_state set sim_time=%s where id=1", (later,))
                    if resolved:
                        await other.execute("update faults set resolved_sim=%s where id=%s", (later, fid))
                moved = True
            return answer

        monkeypatch.setattr(nodes, "_llm", after_model)
        state = await process_signal(conn, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=at)
        assert moved
        sent = await (
            await conn.execute("select sent_sim from notifications where run_id=%s and recipient_type='client'", (run,))
        ).fetchall()
        if resolved:
            assert state["outcome"] == "failed"
            assert any("scope устарел" in error for error in state["errors"])
            assert sent == []
            assert not await (await conn.execute("select 1 from incidents where run_id=%s", (run,))).fetchone()
        else:
            assert sent == [(later,)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config", [None, {}, {"internal": True, "co_team_codes": []}, {"internal": True, "co_team_codes": ["not_a_team"]}]
)
async def test_invalid_native_routing_configuration_never_falls_back(seeded, config):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 invalid routing catalog")
        at = await sim_now(conn)
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        fid = await fault(conn, run, at)
        await operation(conn, run, fid, client, at)
        if config is None:
            await conn.execute("delete from ingest_sources where code='fault_monitor'")
        else:
            await conn.execute("update ingest_sources set config=%s where code='fault_monitor'", (Jsonb(config),))
        with pytest.raises(ValueError, match="fault_monitor"):
            await proactive.produce(conn)
        assert not await (await conn.execute("select 1 from signals where run_id=%s", (run,))).fetchone()


@pytest.mark.asyncio
async def test_fault_resolution_during_fanout_rechecks_each_send_and_rolls_back_step(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 fault resolved during fanout")
        at = await sim_now(conn)
        clients = [
            row[0] for row in await (await conn.execute("select id from clients order by id limit 2")).fetchall()
        ]
        fid = await fault(conn, run, at)
        for client in clients:
            await operation(conn, run, fid, client, at)
            await conn.execute(
                "update clients set consents=jsonb_build_object('proactive',true), "
                "contacts=contacts||jsonb_build_object('preferred','chat') where id=%s",
                (client,),
            )
        [sid] = await proactive.produce(conn)
        await conn.commit()
        original = write.notify_client
        first_attempted = False

        async def resolve_after_first(*args, **kwargs):
            nonlocal first_attempted
            result = await original(*args, **kwargs)
            if not first_attempted:
                assert result["status"] == "sent"
                first_attempted = True
                async with asyncio.timeout(5):
                    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as other:
                        later = at + dt.timedelta(minutes=5)
                        await other.execute("update faults set resolved_sim=%s where id=%s", (later, fid))
                        await other.execute("update sim_state set sim_time=%s where id=1", (later,))
            return result

        monkeypatch.setattr(write, "notify_client", resolve_after_first)
        state = await process_signal(conn, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE)
        assert first_attempted and state["outcome"] == "failed"
        assert any("scope устарел перед инструментом" in error for error in state["errors"])
        assert not await (await conn.execute("select 1 from notifications where run_id=%s", (run,))).fetchone()
        assert not await (await conn.execute("select 1 from incidents where run_id=%s", (run,))).fetchone()
