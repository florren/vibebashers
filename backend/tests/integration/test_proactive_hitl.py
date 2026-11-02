"""T-039: metadata dedup не заменяет обязательное human approval."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from app.agent import proactive
from app.agent.graph import process_signal
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

from .test_proactive_fault import fault, operation


@pytest.mark.asyncio
@pytest.mark.parametrize("competing", [False, True])
async def test_verified_customer_fault_link_is_recorded_while_real_hitl_still_waits(seeded, competing, record_property):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 causal link before HITL")
        at = await sim_now(conn)
        client = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1")
            ).fetchone()
        )[0]
        fid = await fault(conn, run, at)
        op = await operation(conn, run, fid, client, at)
        [service_id] = await proactive.produce(conn)
        await conn.commit()
        service = await process_signal(conn, signal_id=service_id, chain=mock_chain(), profile=MOCK_PROFILE)
        assert service is not None and service["client"] is None
        incident_id = (await (await conn.execute("select id from incidents where run_id=%s", (run,))).fetchone())[0]

        async def economics():
            return await (
                await conn.execute(
                    "select i.mass_impact,e.affected_count,e.potential_loss_rub,e.premium_addon_rub "
                    "from incidents i join incident_economics e on e.incident_id=i.id where i.id=%s",
                    (incident_id,),
                )
            ).fetchone()

        before_economics = await economics()
        if competing:
            competing_at = at + dt.timedelta(seconds=30)
            other_fault = await fault(conn, run, competing_at)
            await operation(conn, run, other_fault, client, competing_at)
            await conn.execute("update sim_state set sim_time=%s where id=1", (competing_at,))
            signals = await proactive.produce(conn)
            [other_signal] = [signal for signal in signals if signal != service_id]
            await conn.commit()
            await process_signal(conn, signal_id=other_signal, chain=mock_chain(), profile=MOCK_PROFILE)
        later = at + dt.timedelta(minutes=1)
        await conn.execute("update sim_state set sim_time=%s where id=1", (later,))
        msg = from_api_signal(
            {
                "client_id": client,
                "channel_code": "chat",
                "text": "Не приходит смс-код для перевода, push тоже не работает. Ошибка уведомлений.",
            }
        )
        msg["meta"].update(source_operation_id=op, source_fault_id=fid)
        result = await create_signal(conn, msg, source_code="api", run_id=run, sim_time=later)
        await conn.commit()
        state = await process_signal(conn, signal_id=result["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
        after_economics = await economics()
        assert after_economics[:2] == before_economics[:2] == (1, 1)
        record_property("economics_before", str(before_economics))
        record_property("economics_after_metadata_hitl", str(after_economics))
        assert state["outcome"] == "awaiting_human"
        assert state["decision"]["needs_human"] is True
        assert state["decision"]["incident_action"] == "link_existing"
        assert state["decision"]["link_incident_id"] == incident_id
        assert await (
            await conn.execute("select incident_id from incident_signals where signal_id=%s", (result["signal_id"],))
        ).fetchall() == [(incident_id,)]
        assert await (
            await conn.execute(
                "select decision,incident_id from human_decisions where agent_run_id=%s", (state["agent_run_id"],)
            )
        ).fetchone() == (None, incident_id)
        assert not await (
            await conn.execute("select 1 from agent_steps where run_id=%s and node='act'", (state["agent_run_id"],))
        ).fetchone()
        assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
        assert await (
            await conn.execute("select incident_id from agent_runs where id=%s", (state["agent_run_id"],))
        ).fetchone() == (incident_id,)
        # Второе обязательное HITL остаётся привязано к тому же уже ожидающему
        # incident; metadata не принимает и не заменяет первое human decision.
        msg["external_id"] = f"T039-second-{run}"
        msg["text"] += " Обращаюсь повторно."
        second = await create_signal(conn, msg, source_code="api", run_id=run, sim_time=later)
        await conn.commit()
        second_state = await process_signal(
            conn, signal_id=second["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE
        )
        assert second_state["outcome"] == "awaiting_human"
        assert (await economics())[:2] == (1, 1)
        assert await (
            await conn.execute("select incident_id from incident_signals where signal_id=%s", (second["signal_id"],))
        ).fetchall() == [(incident_id,)]
        assert await (
            await conn.execute(
                "select decision,incident_id from human_decisions where signal_id in (%s,%s) order by id",
                (result["signal_id"], second["signal_id"]),
            )
        ).fetchall() == [(None, incident_id), (None, incident_id)]


@pytest.mark.asyncio
async def test_native_fault_binding_rejects_conflicts_future_foreign_and_ambiguity(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T039 unique actual causal facts")
        at = await sim_now(conn)
        clients = await (await conn.execute("select id from clients order by id limit 2")).fetchall()
        client, other_client = clients[0][0], clients[1][0]
        fid = await fault(conn, run, at)
        op = await operation(conn, run, fid, client, at)
        other_fault = await fault(conn, run, at)
        other_op = await operation(conn, run, other_fault, client, at)
        foreign_client_op = await operation(conn, run, fid, other_client, at)
        future_op = await operation(conn, run, fid, client, at + dt.timedelta(minutes=1))
        invalid_op = await operation(conn, run, fid, client, at, path="crm")
        unproven_fault = await fault(conn, run, at, emit=False)
        unproven_op = await operation(conn, run, unproven_fault, client, at)

        async def bind(operation_id=None, fault_id=None, candidates=None, expected_run=run):
            return await proactive.causal_fault(
                conn,
                run_id=expected_run,
                client_id=client,
                operation_id=operation_id,
                fault_id=fault_id,
                at=at,
                candidate_operation_ids=candidates,
            )

        assert await bind(op, fid) == fid
        assert await bind(op) == fid
        assert await bind(fault_id=fid) == fid
        assert await bind(candidates=[op]) == fid
        assert await bind(candidates=[op, other_op]) is None
        assert await bind(op, other_fault, [other_op]) is None
        assert await bind(foreign_client_op, fid, [op]) is None
        assert await bind(future_op, fid, [op]) is None
        assert await bind(invalid_op, fid, [op]) is None
        assert await bind(unproven_op, unproven_fault, [op]) is None
        other_run = await new_run(conn, "T039 foreign run")
        assert await bind(op, fid, [op], expected_run=other_run) is None
