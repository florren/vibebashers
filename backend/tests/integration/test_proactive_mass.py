"""Controlled scenario6 proof: actual native 120/90/30, Mock и emulated chat.

Расширяется только собственная synthetic fixture; production lite не обещает
120 подходящих YuFO клиентов. Policy, p/delay/severity и лимиты не меняются.
"""

import asyncio
import datetime as dt
import random

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts.seed.clients import seed_clients

from app.agent.runner import AgentService
from app.ingest.normalizer import create_signal, from_api_signal
from app.sim.behavior import runtime
from app.sim.engine import Simulator
from app.sim.events import EventBus
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

from .test_proactive_fault import fault, operation


@pytest.fixture
def mass_seeded(seeded):
    with psycopg.connect(dsn(seeded)) as conn:
        now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
        # Существующий metadata generator, без генерации новой истории/кассет.
        seed_clients(conn.cursor(), random.Random(42), 5000, now)
    return seeded


@pytest.mark.asyncio
async def test_native_mass_120_90_30_with_actual_owner_care_and_pending_hitl(mass_seeded, record_property):
    url = dsn(mass_seeded)
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=url)
    sim = Simulator(dsn=url)
    try:
        async with await psycopg.AsyncConnection.connect(url) as conn:
            run = await new_run(conn, "T039 controlled scenario6 120/90/30", kind="scenario")
            at = await sim_now(conn)
            policy = await runtime.effective_policy(conn, run, runtime.configured_policy())
            assert policy is not None
            clients = await (
                await conn.execute(
                    "select c.id,c.region_code from clients c join regions r on r.code=c.region_code "
                    "where c.is_active and r.district_code='yufo' and exists(select 1 from client_products cp "
                    "where cp.client_id=c.id and cp.product_code='debit_card' and cp.status='active') order by c.id limit 120"
                )
            ).fetchall()
            assert len(clients) == 120, "insufficient_cohort: нужны 120 actual YuFO debit-card clients"
            people = [row[0] for row in clients]
            for index, person in enumerate(people):
                await conn.execute(
                    "update clients set consents=%s,contacts=contacts||%s where id=%s",
                    (Jsonb({"proactive": index < 90}), Jsonb({"preferred": "chat"}), person),
                )
            fid = await fault(conn, run, at, emit=False)
            # Полный native schedule fixture: 90 — существующий duration из
            # World.gen_faults, не новый policy/delay/порог и не ответ модели.
            await EventBus(conn).emit(
                run,
                "fault.started",
                {
                    "fault_id": fid,
                    "system": "notification_gw",
                    "error_code": "NOTIF-DELAY",
                    "started_sim": at.isoformat(),
                    "expected_duration_min": 90,
                    "impact_count": 0,
                    "affected_clients": 0,
                },
                at,
            )
            await conn.execute(
                "update faults set region_codes=%s where id=%s", (sorted({row[1] for row in clients}), fid)
            )
            operations = {}
            for person in people:
                operations[person] = await operation(conn, run, fid, person, at)
            await conn.commit()
            await sim.load_state()
            # Controlled clock fixture: не добавляем посторонние случайные ops/faults.
            # Все 120 исходных failed ops — native persisted facts, не payload counters.
            sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
            await sim.step(1)
            episodes = await (
                await conn.execute(
                    "select count(*),count(first_complaint_sim) from behavior_runtime where run_id=%s", (run,)
                )
            ).fetchone()
            assert episodes == (120, 0)
            await conn.commit()
            await service._proactive_cycle()
            await asyncio.gather(*list(service._inflight))
            assert service.failed == 0
            notices = await (
                await conn.execute(
                    "select client_id,sent_sim from notifications where run_id=%s and template_code='proactive_fault' "
                    "and status='sent' order by client_id",
                    (run,),
                )
            ).fetchall()
            assert len(notices) == 90 and {row[0] for row in notices} == set(people[:90])
            assert all(row[1] == at + dt.timedelta(minutes=1) for row in notices)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from signals where run_id=%s and origin is distinct from 'proactive'", (run,)
                    )
                ).fetchone()
            ) == (0,)
            await conn.commit()
            await sim.step(0.1)
            care = await (
                await conn.execute(
                    "select b.client_id,c.care_score,b.first_complaint_sim from behavior_runtime b "
                    "join client_states c on c.id=b.state_id where b.run_id=%s",
                    (run,),
                )
            ).fetchall()
            assert len(care) == 120 and all(row[2] is None for row in care)
            assert {row[0] for row in care if float(row[1]) > 0} == set(people[:90])
            now = await sim_now(conn)
            complaint_ids = []
            for person in people[90:]:
                msg = from_api_signal(
                    {
                        "client_id": person,
                        "channel_code": "chat",
                        "text": "Не приходит смс-код для перевода, push тоже не работает. Ошибка уведомлений.",
                    }
                )
                msg["origin"] = "scenario"
                msg["external_id"] = f"T039-complaint-{run}-{person}"
                msg["meta"].update(source_operation_id=operations[person], source_fault_id=fid)
                result = await create_signal(conn, msg, source_code="api", run_id=run, sim_time=now)
                complaint_ids.append(result["signal_id"])
            await conn.commit()
            await asyncio.gather(*(service.submit(sid) for sid in complaint_ids))
            assert service.failed == 0
            actual = await (
                await conn.execute(
                    "select i.id,i.mass_impact,e.affected_count from incidents i join incident_economics e on e.incident_id=i.id where i.run_id=%s",
                    (run,),
                )
            ).fetchall()
            assert len(actual) == 1 and actual[0][1:] == (120, 120)
            linked = await (
                await conn.execute(
                    "select signal_id from incident_signals where incident_id=%s and signal_id=any(%s)",
                    (actual[0][0], complaint_ids),
                )
            ).fetchall()
            assert {row[0] for row in linked} == set(complaint_ids)
            first_complaint = (
                await (
                    await conn.execute("select min(received_sim) from signals where id=any(%s)", (complaint_ids,))
                ).fetchone()
            )[0]
            assert max(row[1] for row in notices) < first_complaint
            pending = (
                await (
                    await conn.execute(
                        "select count(*) from human_decisions where sim_run_id=%s and decision is null", (run,)
                    )
                ).fetchone()
            )[0]
            assert not await (await conn.execute("select 1 from ledger_entries where run_id=%s", (run,))).fetchone()
            await conn.commit()
            await sim.step(0.1)
            owner_complaints = await (
                await conn.execute(
                    "select count(*) from behavior_runtime where run_id=%s and first_complaint_sim is not null",
                    (run,),
                )
            ).fetchone()
            assert owner_complaints == (30,)
            timer_counts = await (
                await conn.execute(
                    "select kind,status,count(*) from behavior_work where run_id=%s group by kind,status order by kind,status",
                    (run,),
                )
            ).fetchall()
            record_property("actual_owner_timers", str(timer_counts))
            record_property(
                "native_facts",
                str(
                    {
                        "affected": 120,
                        "sent_emulated": len(notices),
                        "complaints": len(linked),
                        "care_positive": 90,
                        "pending_human": pending,
                        "prevented_complaints": None,
                        "prevention_basis": "not_modelled",
                    }
                ),
            )
    finally:
        await service.stop()
        if sim.conn is not None:
            await sim.conn.close()
