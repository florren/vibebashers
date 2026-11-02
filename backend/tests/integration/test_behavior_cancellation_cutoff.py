"""T039 B: logical T5 отдельно от наблюдения жалобы T8 при horizon T9."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from app.sim.behavior.cancellation_details import CancellationDetails
from app.sim.behavior.owner import BehaviorOwner
from app.sim.behavior.prevention import summarize
from tests.helpers import dsn

from .test_behavior_cancellation_runtime import opened, receipts, resolved
from .test_behavior_owner import POLICY
from .test_behavior_signal_evidence import source


@pytest.mark.asyncio
@pytest.mark.parametrize("processed,classified", [(True, True), (False, True), (False, False)])
async def test_late_t5_resolution_and_t8_complaint_observed_at_t9_never_receive_credit(seeded, processed, classified):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, operation, fault, due = await opened(conn)
        t5, t8, t9 = (now + dt.timedelta(minutes=n) for n in (5, 8, 9))
        assert due > t9  # Прежний успешный p_complain draw и native due, без подбора.
        await conn.execute("update sim_state set sim_time=%s where id=1", (t8 if processed else t9,))
        signal, _ = await source(conn, run, client, t8, canonical=classified)
        await conn.execute(
            "update signals set source_operation_id=%s,source_fault_id=%s where id=%s", (operation, fault, signal)
        )
        primary_before = []
        if processed:
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=t8)
            primary_before = [r for r in await receipts(conn, run) if r["details"]["work_kind"] == "complaint"]
            assert len(primary_before) == 1 and primary_before[0]["action"] == "already_complained"
        incident = await resolved(conn, run, client, fault, t5)
        await conn.execute(
            "insert into incident_signals(incident_id,signal_id,linked_sim) values(%s,%s,%s)", (incident, signal, t9)
        )
        await conn.execute("update sim_state set sim_time=%s where id=1", (t9,))
        # Позднее native resolution не переписывает существующие first/work facts.
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=t9)
        records = await receipts(conn, run)
        primary = [r for r in records if r["details"]["work_kind"] == "complaint"]
        assert len(primary) == 1
        if processed:
            assert primary == primary_before
            current = await BehaviorOwner(conn, POLICY).episode(run, client)
            assert current["first_complaint_sim"] == t8 and current["closed_sim"] == t5
            assert any(r["action"] == "cancelled_by_resolution" for r in records)
        else:
            details = CancellationDetails.from_json(primary[0]["details"])
            assert primary[0]["action"] == "cancelled_by_resolution"
            assert details.first_complaint_sim_at_cancellation is None
            assert details.resolution_sim == details.cancellation_sim == t5
            assert details.cancellation_observed_sim == t9
        for record in records:
            details = CancellationDetails.from_json(record["details"])
            if record["action"] == "cancelled_by_resolution":
                assert details.first_complaint_sim_at_cancellation is None
                assert details.cancellation_sim == t5 and details.cancellation_observed_sim == t9
        result = await summarize(conn, run_id=run)
        assert result.modelled_prevented_by_resolution == (0 if classified else None)
        assert result.recorded_eligible_count == 0
