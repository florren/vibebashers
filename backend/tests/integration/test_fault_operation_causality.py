"""T-039: реальная fault причинность, прежняя RNG последовательность и retry."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from app.sim.events import EventBus
from app.sim.generators import World
from app.sim.rng import SimRng
from tests.helpers import dsn, new_run, sim_now


class RetryBatch(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_future_fault_never_fails_earlier_operation_and_keeps_rng_retry(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        now = await sim_now(conn)
        run = await new_run(conn, "T039 temporal cause", kind="free")
        fault = (
            await (
                await conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s) returning id",
                    (run, now),
                )
            ).fetchone()
        )[0]
        await EventBus(conn).emit(
            run,
            "fault.started",
            {
                "fault_id": fault,
                "system": "sub_deposits",
                "error_code": "DEP-TIMEOUT-503",
                "started_sim": now.isoformat(),
                "expected_duration_min": 90,
            },
            now,
        )
        await conn.commit()

        async def batch(starts: dt.datetime, *, rollback: bool):
            await conn.execute("update faults set started_sim=%s where id=%s", (now, fault))
            await conn.commit()
            rng = SimRng(918)
            world = World(conn, EventBus(conn), rng, run, intensities={"op": 120})
            await world.load()
            # После load меняется authoritative row: cache времени намеренно
            # устарел, как и в прочих boundary cases этого файла.
            await conn.execute("update faults set started_sim=%s where id=%s", (starts, fault))
            events_before = await (
                await conn.execute(
                    "select event_type,payload,correlation_id from sim_events where run_id=%s order by id", (run,)
                )
            ).fetchall()
            client = next(row for row in world.clients if "deposit" in row.products)
            client.products = ["deposit"]
            world.clients, world.scale = [client], 1.0
            await conn.commit()
            captured = None
            try:
                async with conn.transaction():
                    count = await world.gen_operations(now, 60)
                    rows = await (
                        await conn.execute(
                            "select product_code,op_type,system_path,amount_rub,method,started_sim,finished_sim,status,error_code,fault_id from operations where run_id=%s order by id",
                            (run,),
                        )
                    ).fetchall()
                    captured = (
                        count,
                        rows,
                        rng.dump_state(),
                        [(p.due_sim, p.error_code, p.source_fault_id) for p in world.pending],
                    )
                    if rollback:
                        raise RetryBatch("injected failure after actual operations/events/ABS writes")
            except RetryBatch:
                assert (
                    await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()
                ) == (0,)
                assert (
                    await (
                        await conn.execute(
                            "select event_type,payload,correlation_id from sim_events where run_id=%s order by id",
                            (run,),
                        )
                    ).fetchall()
                ) == events_before
                await conn.rollback()
            assert captured is not None
            return captured

        control = await batch(now, rollback=True)
        future = now + dt.timedelta(minutes=30)
        first = await batch(future, rollback=True)
        retry = await batch(future, rollback=False)
        assert first == retry
        assert first[0] > 50 and len(first[1]) == first[0]
        assert first[2] == control[2]  # Полная Random state, включая gauss cache.
        assert [row[:7] for row in first[1]] == [row[:7] for row in control[1]]
        before = [row for row in first[1] if row[5] < future]
        failed = [row for row in first[1] if row[7] == "failed"]
        assert before and failed
        assert all(row[7:] == ("success", None, None) for row in before)
        assert all(row[5] >= future and row[8:] == ("DEP-TIMEOUT-503", fault) for row in failed)
        assert all(due >= future and code == "DEP-TIMEOUT-503" and source == fault for due, code, source in first[3])
        assert len(first[3]) < len(control[3])  # Невалидная причина не создаёт pending.
        assert (
            await (
                await conn.execute(
                    "select count(*) from operations o join faults f on f.id=o.fault_id join clients c on c.id=o.client_id where o.run_id=%s and (f.run_id<>o.run_id or not f.system_code=any(o.system_path) or f.error_code<>o.error_code or o.started_sim<f.started_sim or (f.resolved_sim is not null and o.started_sim>=f.resolved_sim) or (cardinality(f.region_codes)>0 and not c.region_code=any(f.region_codes)))",
                    (run,),
                )
            ).fetchone()
        ) == (0,)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["foreign_run", "region", "resolved", "wrong_code_cache"])
async def test_actual_fault_boundary_rejects_foreign_region_closed_or_stale_cache(seeded: str, invalid: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        now = await sim_now(conn)
        run = await new_run(conn, "T039 source boundaries", kind="free")
        foreign = await new_run(conn, "T039 foreign fault", kind="scenario")
        rng = SimRng(918)
        world = World(conn, EventBus(conn), rng, run, intensities={"op": 120})
        await world.load()
        client = next(row for row in world.clients if "deposit" in row.products)
        client.products = ["deposit"]
        world.clients, world.scale = [client], 1.0
        region = "78" if client.region_code != "78" else "77"
        fault = (
            await (
                await conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim,resolved_sim,region_codes) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s,%s,%s) returning id",
                    (
                        foreign if invalid == "foreign_run" else run,
                        now,
                        now if invalid == "resolved" else None,
                        [region] if invalid == "region" else [],
                    ),
                )
            ).fetchone()
        )[0]
        import uuid

        # Моделируем устаревший cache; authoritative rows остаются настоящими.
        world.active_faults = [
            {
                "id": fault,
                "system": "sub_deposits",
                "error_code": "APP-LOGIN-401" if invalid == "wrong_code_cache" else "DEP-TIMEOUT-503",
                "started_sim": now,
                "impact": 0,
                "clients": set(),
                "corr": uuid.uuid4(),
            }
        ]
        await world.gen_operations(now, 60)
        assert (
            await (
                await conn.execute(
                    "select count(*) from operations where run_id=%s and (status<>'success' or error_code is not null or fault_id is not null)",
                    (run,),
                )
            ).fetchone()
        ) == (0,)
        assert world.pending == []
        await conn.rollback()
