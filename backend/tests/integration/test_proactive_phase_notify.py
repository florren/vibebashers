"""PG16 protocol-only roundtrip: no sim_events rows/operational phase claims."""

import datetime as dt
import json

import psycopg
import pytest

from app.sim.events import EventBus
from tests.helpers import dsn
from tests.unit.test_proactive_phase_payload import BASE, BIG, PARTS, Connection


@pytest.mark.asyncio
async def test_maximum_typed_envelopes_reach_postgres_notify_without_clipping(db_url):
    # Отдельный channel исключает wake реальных actors. Это protocol fixture,
    # synthetic IDs не записываются как operational evidence в sim_events.
    async with (
        await psycopg.AsyncConnection.connect(dsn(db_url), autocommit=True) as listener,
        await psycopg.AsyncConnection.connect(dsn(db_url), autocommit=True) as sender,
    ):
        await listener.execute("LISTEN t039_protocol_fixture")
        expected = []
        for phase, fields in PARTS.items():
            capture = Connection()
            await EventBus(capture).emit(
                BIG,
                f"scenario.proactive_{phase}",
                {**BASE, **fields},
                dt.datetime(2026, 11, 2, tzinfo=dt.UTC),
                scenario_id="mass_notifications",
            )
            expected.append(capture.notify)
            await sender.execute("select pg_notify('t039_protocol_fixture',%s)", (capture.notify,))
        received = [notice.payload async for notice in listener.notifies(timeout=5, stop_after=len(expected))]
        assert received == expected
        assert all(len(payload.encode("utf-8")) < 8000 for payload in received)
        assert len(json.loads(received[0])["payload"]["operation_ids"]) == 120
        assert len(json.loads(received[1])["payload"]["notification_ids"]) == 120
        assert len(json.loads(received[2])["payload"]["complaint_signal_ids"]) == 30
