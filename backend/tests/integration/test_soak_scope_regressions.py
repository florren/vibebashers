"""Дефекты длинного native soak: optional city и несвязанный fault hint перед HITL."""

import datetime as dt
import uuid

import psycopg
import pytest

from app.agent.graph import process_signal
from app.ingest.normalizer import create_signal, from_api_signal
from app.sim.engine import Simulator
from app.sim.generators import PendingSignal
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

from .test_behavior_runtime import POLICY, setup
from .test_proactive_fault import fault, operation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("city", ["", None, 10])
async def test_pending_city_preserves_unknown_string_but_rejects_wrong_types(seeded, monkeypatch, city):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        world = await sim._ensure_world()
        person = next(item for item in world.clients if item.id == client)
        person.city = city
        person.channel_weights = {"chat": 1.0}
        due = now + dt.timedelta(minutes=10)
        world.pending.append(
            PendingSignal(due, person, "client_error", "deposit", None, None, None, None, uuid.uuid4())
        )
        await sim.step(1)
        await sim.conn.close()
        restored = Simulator(dsn=seeded, behavior_policy=POLICY)
        await restored.load_state()
        restored._intensities = dict(sim._intensities)
        try:
            if city != "":
                with pytest.raises(ValueError, match="строковые client attributes"):
                    await restored.step(9)
                assert restored.clock.sim_time == now + dt.timedelta(minutes=1)
            else:
                await restored.step(9)
                row = await (await conn.execute("select received_sim from signals where run_id=%s", (run,))).fetchone()
                assert row == (due,)
        finally:
            await restored.conn.close()


async def test_unrelated_failed_operation_hint_does_not_rebind_generic_hitl(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "generic HITL with unrelated fault history")
        now = await sim_now(conn)
        client = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1")
            ).fetchone()
        )[0]
        fid = await fault(conn, run, now)
        await operation(conn, run, fid, client, now)
        text = "Клиент: В заявке на «дебетовая карта» я перепутал цифры и уже подтвердил. Помогите исправить мои данные.\nОператор: Сообщение принято."

        async def signal():
            return await create_signal(
                conn,
                from_api_signal({"channel_code": "chat", "client_id": client, "text": text}),
                source_code="api",
                run_id=run,
                sim_time=now,
            )

        original = await signal()
        incident = (
            await (
                await conn.execute(
                    "insert into incidents(run_id,title,incident_type,system_code,product_code,team_code,primary_client_id,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) values(%s,'Ошибка клиента','client_error','processing','debit_card','team_cx',%s,'easy','low',3,'in_progress','scenario',%s,%s,%s) returning id",
                    (run, client, now, now + dt.timedelta(days=1), now + dt.timedelta(hours=1)),
                )
            ).fetchone()
        )[0]
        await conn.execute(
            "insert into incident_signals(incident_id,signal_id,linked_sim) values(%s,%s,%s)",
            (incident, original["signal_id"], now),
        )
        current = await signal()
        await conn.commit()
        state = await process_signal(conn, signal_id=current["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
        assert state["context"]["hints"]["fault_id"] == fid
        assert state["classification"].get("error_code") is None
        assert state["outcome"] == "awaiting_human"
        assert state["decision"]["link_incident_id"] == incident
        decision = await (
            await conn.execute(
                "select incident_id,decision from human_decisions where signal_id=%s", (current["signal_id"],)
            )
        ).fetchone()
        assert decision == (incident, None)
        assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
