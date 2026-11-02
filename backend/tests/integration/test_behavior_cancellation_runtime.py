"""T039 B: настоящие native причины/receipts, без изменения policy draws."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.sim.behavior.cancellation_details import CancellationDetails
from app.sim.behavior.owner import BehaviorOwner
from app.sim.behavior.prevention import summarize
from app.sim.behavior.store import BehaviorStore
from tests.helpers import dsn

from .test_behavior_owner import POLICY, prepare
from .test_behavior_signal_evidence import source


async def opened(conn):
    run, client, now, _, operations = await prepare(conn)
    async with conn.transaction():
        await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
    due = (
        await (
            await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
        ).fetchone()
    )[0]
    assert due > now + dt.timedelta(seconds=1)
    fault = (await (await conn.execute("select fault_id from operations where id=%s", (operations[0],))).fetchone())[0]
    return run, client, now, operations[0], fault, due


async def resolved(conn, run, client, fault, at):
    incident = (
        await (
            await conn.execute(
                "insert into incidents(run_id,title,incident_type,product_code,system_code,team_code,complexity,criticality,priority,status,created_by,created_sim,resolved_sim,sla_due_sim,take_due_sim,fault_id,primary_client_id) "
                "values(%s,'synthetic native resolution','tech_fault','deposit','sub_deposits','team_deposits','medium','high',2,'resolved','behavior_model',%s,%s,%s,%s,%s,%s) returning id",
                (run, at, at, at + dt.timedelta(days=1), at + dt.timedelta(hours=1), fault, client),
            )
        ).fetchone()
    )[0]
    await conn.execute("update faults set resolved_sim=%s where id=%s", (at, fault))
    assert await BehaviorStore(conn).enqueue_resolution(run_id=run, client_id=client, incident_id=incident)
    return incident


async def receipts(conn, run):
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select * from behavior_receipts where run_id=%s and source_kind='work' order by source_id", (run,)
        )
        return await cur.fetchall()


@pytest.mark.asyncio
async def test_resolution_cancels_primary_and_patience_atomically_with_native_time_and_retry(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        before = (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0]
        at = now + dt.timedelta(seconds=1)
        incident = await resolved(conn, run, client, fault, at)
        horizon = at + dt.timedelta(minutes=1)
        after = await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=horizon)
        assert after == before
        records = await receipts(conn, run)
        assert len(records) == 2
        assert {r["action"] for r in records} == {"cancelled_by_resolution"}
        assert {r["details"]["work_kind"] for r in records} == {"complaint", "patience"}
        for record in records:
            details = CancellationDetails.from_json(record["details"])
            assert details.cancellation_sim == at and details.cancellation_observed_sim == horizon
            assert details.resolution_sim == at and details.evidence_source_id == incident
            assert details.first_complaint_sim_at_cancellation is None and details.complaint_observation_complete
            assert details.due_sim > details.resolution_sim
        summary = await summarize(conn, run_id=run)
        assert summary.modelled_prevented_by_resolution == 1 and summary.recorded_eligible_count == 1
        assert summary.unknown_cancelled_work_count == 0 and summary.recorded_cancellation_count == 2
        await conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        async with conn.transaction():
            assert await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=horizon) == before
        assert await receipts(conn, run) == records
        assert (
            await (
                await conn.execute("select count(*) from behavior_work where run_id=%s and status='pending'", (run,))
            ).fetchone()
        ) == (0,)


@pytest.mark.asyncio
async def test_receipt_failure_rolls_back_cancellation_closure_and_rng_before_retry(seeded, monkeypatch):
    from app.sim.behavior import cancellation

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        at = now + dt.timedelta(seconds=1)
        await resolved(conn, run, client, fault, at)
        before_rng = (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0]
        await conn.commit()
        original = cancellation.CancellationDetails.to_json

        calls = 0

        def broken(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected cancellation receipt")
            return original(self)

        monkeypatch.setattr(cancellation.CancellationDetails, "to_json", broken)
        with pytest.raises(RuntimeError, match="injected cancellation receipt"):
            async with conn.transaction():
                await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=at)
        assert calls == 2  # Первый receipt/status уже записан, но общий TX откатил оба.
        assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0] == before_rng
        assert await receipts(conn, run) == []
        assert (
            await (await conn.execute("select closed_sim from behavior_runtime where run_id=%s", (run,))).fetchone()
        ) == (None,)
        assert (
            await (
                await conn.execute("select count(*) from behavior_work where run_id=%s and status='pending'", (run,))
            ).fetchone()
        ) == (2,)
        await conn.rollback()
        monkeypatch.setattr(cancellation.CancellationDetails, "to_json", original)
        async with conn.transaction():
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=at)
        assert len(await receipts(conn, run)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classified, sentiment, expected_complete, expected_first",
    [
        (False, "negative", False, False),
        (True, "negative", True, True),
        (True, "neutral", True, False),
    ],
)
async def test_native_complaint_received_before_resolution_is_not_hidden_by_late_observation(
    seeded,
    classified,
    sentiment,
    expected_complete,
    expected_first,
):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        signal, ctx = await source(conn, run, client, now, sentiment=sentiment, canonical=classified)
        await conn.execute(
            "update signals set source_operation_id=%s,source_fault_id=%s where id=%s", (op, fault, signal)
        )
        # Source helper фиксирует classifier observation at T0; переносим лишь
        # admission evidence в T5 для delayed model boundary, received_sim остаётся T0.
        at = now + dt.timedelta(seconds=1)
        horizon = now + dt.timedelta(minutes=1)
        await conn.execute(
            "update behavior_evidence set observed_sim=%s where run_id=%s and source_kind='agent_state'", (horizon, run)
        )
        await resolved(conn, run, client, fault, at)
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=horizon)
        primary = [r for r in await receipts(conn, run) if r["details"]["work_kind"] == "complaint"]
        assert len(primary) == 1 and primary[0]["action"] == "cancelled_by_resolution"
        details = CancellationDetails.from_json(primary[0]["details"])
        assert details.complaint_observation_complete is expected_complete
        assert details.first_complaint_sim_at_cancellation == (now if expected_first else None)
        assert details.resolution_sim == at and details.cancellation_observed_sim == horizon
        summary = await summarize(conn, run_id=run)
        assert summary.modelled_prevented_by_resolution == (
            None if not expected_complete else 0 if expected_first else 1
        )
        assert summary.unknown_cancelled_work_count == (0 if expected_complete else 1)


@pytest.mark.asyncio
async def test_already_complained_records_canonical_evidence_without_prevention(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        await conn.execute("update sim_state set sim_time=%s where id=1", (now + dt.timedelta(seconds=1),))
        signal, _ = await source(conn, run, client, now + dt.timedelta(seconds=1))
        await conn.execute(
            "update signals set source_operation_id=%s,source_fault_id=%s where id=%s", (op, fault, signal)
        )
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now + dt.timedelta(seconds=1))
        records = await receipts(conn, run)
        assert len(records) == 1 and records[0]["action"] == "already_complained"
        details = CancellationDetails.from_json(records[0]["details"])
        assert details.canonical_signal_id == signal and details.resolution_sim is None
        assert details.first_complaint_sim_at_cancellation == now + dt.timedelta(seconds=1)
        assert details.work_kind == "complaint"
        summary = await summarize(conn, run_id=run)
        assert summary.modelled_prevented_by_resolution == 0 and summary.recorded_eligible_count == 0
        assert (
            await (
                await conn.execute("select status from behavior_work where run_id=%s and kind='patience'", (run,))
            ).fetchone()
        ) == ("pending",)


@pytest.mark.asyncio
async def test_two_connections_cancel_once_without_rng_draw(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        at = now + dt.timedelta(seconds=1)
        await resolved(conn, run, client, fault, at)
        before = (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0]
        await conn.commit()

    async def tick():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            async with conn.transaction():
                return await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=at)

    a, b = await asyncio.gather(tick(), tick())
    assert a == b == before
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        assert len(await receipts(conn, run)) == 2
        assert (await summarize(conn, run_id=run)).modelled_prevented_by_resolution == 1


@pytest.mark.asyncio
async def test_all_causes_last_resolution_not_observation_tick_and_foreign_evidence_rejected(seeded):
    from app.sim.behavior.cancellation import cancel_pending

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        other = (
            await (
                await conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s) returning id",
                    (run, now),
                )
            ).fetchone()
        )[0]
        second = (
            await (
                await conn.execute(
                    "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) values(%s,%s,'deposit','deposit_open',ARRAY['sub_deposits'],'failed','DEP-TIMEOUT-503',%s,%s) returning id",
                    (run, client, other, now),
                )
            ).fetchone()
        )[0]
        await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=second)
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
        first_at, last_at = now + dt.timedelta(seconds=1), now + dt.timedelta(seconds=2)
        await resolved(conn, run, client, fault, first_at)
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=first_at)
        assert await receipts(conn, run) == []
        assert (await summarize(conn, run_id=run)).modelled_prevented_by_resolution == 0
        await resolved(conn, run, client, other, last_at)
        current = await BehaviorOwner(conn, POLICY).episode(run, client)
        # Даже реальный evidence другого клиента нельзя приклеить текущему episode.
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "select * from behavior_evidence where run_id=%s and source_kind='resolution' order by id desc limit 1",
                (run,),
            )
            evidence = await cur.fetchone()
        other_client = (
            await (await conn.execute("select id from clients where id<>%s order by id limit 1", (client,))).fetchone()
        )[0]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "insert into behavior_evidence(run_id,client_id,source_kind,source_id,observed_sim) values(%s,%s,'resolution',%s,%s) returning *",
                (run, other_client, evidence["source_id"], last_at),
            )
            foreign_evidence = await cur.fetchone()
        with pytest.raises(ValueError, match="native same-run/client"):
            await cancel_pending(conn, current, foreign_evidence, at=last_at, observed_at=last_at)
        # Fixture foreign evidence не поступает owner: нет episode этого клиента.
        await conn.execute("delete from behavior_evidence where id=%s", (foreign_evidence["id"],))
        horizon = last_at + dt.timedelta(minutes=1)
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=horizon)
        records = await receipts(conn, run)
        assert len(records) == 2
        assert {r["details"]["resolution_sim"] for r in records} == {last_at.isoformat()}
        assert {r["details"]["cancellation_observed_sim"] for r in records} == {horizon.isoformat()}
        assert (await summarize(conn, run_id=run)).modelled_prevented_by_resolution == 1


@pytest.mark.asyncio
async def test_legacy_null_and_unlinked_rich_receipt_remain_unknown_not_zero(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        work = (
            await (
                await conn.execute("select id from behavior_work where run_id=%s and kind='complaint'", (run,))
            ).fetchone()
        )[0]
        await conn.execute("update behavior_work set status='cancelled',consumed_sim=%s where id=%s", (now, work))
        await conn.execute(
            "insert into behavior_receipts(run_id,client_id,source_kind,source_id,action,consumed_sim) values(%s,%s,'work',%s,'cancelled_by_resolution',%s)",
            (run, client, work, now),
        )
        summary = await summarize(conn, run_id=run)
        assert summary.modelled_prevented_by_resolution is None
        assert summary.recorded_eligible_count == 0 and summary.unknown_cancelled_work_count == 1
        assert summary.quality == "incomplete"
        assert (
            await (
                await conn.execute(
                    "select details from behavior_receipts where run_id=%s and source_kind='work'", (run,)
                )
            ).fetchone()
        ) == (None,)
        rich_without_native_evidence = CancellationDetails(
            1,
            "complaint",
            due,
            now,
            now,
            None,
            True,
            1000000,
            "resolution",
            1000001,
            None,
            now,
        ).to_json()
        await conn.execute(
            "update behavior_receipts set details=%s where run_id=%s and source_kind='work'",
            (Jsonb(rich_without_native_evidence), run),
        )
        assert (await summarize(conn, run_id=run)).modelled_prevented_by_resolution is None
        assert (await summarize(conn, run_id=run)).unknown_cancelled_work_count == 1
        # Другой run/baseline не получает известный zero без behavior marker.
        baseline = (
            await (await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")).fetchone()
        )[0]
        assert (await summarize(conn, run_id=baseline)).modelled_prevented_by_resolution is None


@pytest.mark.asyncio
async def test_reader_does_not_credit_late_committed_prior_input_with_unknown_classification(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, op, fault, due = await opened(conn)
        at = now + dt.timedelta(seconds=1)
        await resolved(conn, run, client, fault, at)
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=at)
        assert (await summarize(conn, run_id=run)).modelled_prevented_by_resolution == 1
        # Незавершённая параллельная TX могла быть невидима при отмене. Receipt
        # immutable; reader перепроверяет новые actual facts и не сохраняет credit.
        await conn.commit()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as late_conn:
            signal, _ = await source(late_conn, run, client, now, canonical=False)
            await late_conn.execute(
                "update signals set source_operation_id=%s,source_fault_id=%s where id=%s", (op, fault, signal)
            )
            await late_conn.commit()
        assert (await summarize(conn, run_id=run)).modelled_prevented_by_resolution is None
        assert (await summarize(conn, run_id=run)).recorded_eligible_count == 0
        primary = [r for r in await receipts(conn, run) if r["details"]["work_kind"] == "complaint"]
        assert primary[0]["details"]["complaint_observation_complete"] is True
