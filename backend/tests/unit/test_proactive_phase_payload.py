"""Typed native journal: максимальные bigint IDs помещаются в PG NOTIFY целиком."""

import datetime as dt
import json
import uuid

import pytest

from app.contracts.registry import validate
from app.sim.events import EventBus, EventValidationError

BIG = 2**63 - 1
BASE = {"version": 1, "scenario_id": "mass_notifications", "script_sha256": "f" * 64, "fault_id": BIG}
PARTS = {
    "prepared": {"operation_ids": [BIG - i for i in range(120)]},
    "notified": {
        "prepared_event_id": BIG,
        "agent_run_id": BIG,
        "anchor_signal_id": BIG,
        "notification_ids": [BIG - i for i in range(120)],
    },
    "complaints": {
        "prepared_event_id": BIG,
        "notified_event_id": BIG,
        "complaint_signal_ids": [BIG - i for i in range(30)],
    },
    "completed": {
        "prepared_event_id": BIG,
        "notified_event_id": BIG,
        "complaints_event_id": BIG,
        "incident_id": BIG,
        "care_positive": 120,
    },
    "failed": {"prepared_event_id": BIG, "reason": "inconsistent_evidence"},
}


class Connection:
    def __init__(self):
        self.stored, self.notify = None, None

    async def execute(self, query, args):
        if query.startswith("insert into sim_events"):
            self.stored = json.loads(args[2])
        elif query.startswith("select pg_notify"):
            self.notify = args[0]
        else:
            raise AssertionError(query)
        return self

    async def fetchone(self):
        return (BIG,)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", PARTS)
async def test_each_complete_maximum_phase_is_lossless_under_8k_notify(phase, record_property):
    conn = Connection()
    payload = {**BASE, **PARTS[phase]}
    event_type = f"scenario.proactive_{phase}"
    at = dt.datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=dt.UTC)
    await EventBus(conn).emit(
        BIG, event_type, payload, at, correlation_id=uuid.UUID(int=2**128 - 1), scenario_id="mass_notifications"
    )
    assert conn.notify is not None
    envelope = json.loads(conn.notify)
    assert len(conn.notify.encode("utf-8")) < 8000
    assert envelope["payload"] == conn.stored == {**payload, "event_type": event_type}
    assert not validate(envelope, "envelope")
    assert not validate(envelope["payload"], "sim/scenario_proactive")
    record_property("notify_utf8_bytes", len(conn.notify.encode("utf-8")))


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["too_many", "duplicate", "other_phase_evidence", "raw_error", "huge_id"])
async def test_invalid_or_unbounded_phase_evidence_is_rejected_before_sql(invalid):
    payload = {**BASE, **PARTS["prepared"]}
    if invalid == "too_many":
        payload["operation_ids"] = list(range(1, 122))
    elif invalid == "duplicate":
        payload["operation_ids"] = [1] * 120
    elif invalid == "other_phase_evidence":
        payload["notification_ids"] = list(range(1, 121))
    elif invalid == "raw_error":
        payload["reason"] = "unbounded external body"
    else:
        payload["fault_id"] = BIG + 1
    conn = Connection()
    with pytest.raises(EventValidationError):
        await EventBus(conn).emit(BIG, "scenario.proactive_prepared", payload, dt.datetime(2026, 11, 2, tzinfo=dt.UTC))
    assert conn.stored is conn.notify is None
