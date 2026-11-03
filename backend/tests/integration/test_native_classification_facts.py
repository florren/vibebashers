"""Настоящие producer/fault/operation → graph: catalog system не подменяется эвристикой."""

import psycopg
import pytest

from app.agent import proactive
from app.agent.graph import process_signal
from app.economics import dcltv
from app.sim.events import EventBus
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now


@pytest.mark.parametrize(
    "product,system,code",
    [
        ("debit_card", "promo_engine", "PROMO-ELIGIBILITY-FAIL"),
        ("credit", "notification_gw", "NOTIF-OTP-MISSING"),
        ("debit_card", "core_abs", "ABS-BALANCE-MISMATCH"),
    ],
)
async def test_verified_native_shared_system_routes_without_fabricated_economics(seeded, product, system, code):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "native catalog facts regression")
        at = await sim_now(conn)
        client = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        fault = (
            await (
                await conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim) values(%s,%s,%s,%s) returning id",
                    (run, system, code, at),
                )
            ).fetchone()
        )[0]
        await EventBus(conn).emit(
            run,
            "fault.started",
            {
                "fault_id": fault,
                "system": system,
                "error_code": code,
                "started_sim": at.isoformat(),
                "expected_duration_min": 90,
                "impact_count": 0,
                "affected_clients": 0,
            },
            at,
        )
        await conn.execute(
            "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) "
            "values(%s,%s,%s,'transfer',%s,'failed',%s,%s,%s)",
            (run, client, product, [system], code, fault, at),
        )
        scope = await proactive.fault_scope(conn, run, fault, at)
        assert (scope["product_code"], scope["system_code"], scope["affected_count"]) == (product, system, 1)
        [signal] = await proactive.produce(conn)
        await conn.commit()
        state = await process_signal(conn, signal_id=signal, chain=mock_chain(), profile=MOCK_PROFILE)
        assert state["outcome"] == "deferred"
        incident = await (
            await conn.execute(
                "select id,product_code,system_code,error_code,fault_id from incidents where run_id=%s",
                (run,),
            )
        ).fetchone()
        assert incident and incident[1:] == (product, system, code, fault)
        economics = await dcltv.compute_incident(conn, incident[0], sim_time=at)
        assert economics["affected_count"] == 1
        assert (await (await conn.execute("select count(*) from ledger_entries where run_id=%s", (run,))).fetchone())[
            0
        ] == 0
