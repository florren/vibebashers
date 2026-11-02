"""Настоящие DB leases/commits; Sender fake, Telegram HTTP никогда не вызывается."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.sim import run_lifecycle
from app.sim.maintenance import MaintenanceBusy
from app.sim.maintenance_db import DatabaseBoundary
from app.tgbot.configuration import TransportConfiguration
from app.tgbot.delivery import deliver_once
from app.tgbot.outbox import enqueue_notification, enqueue_reply
from app.tgbot.telegram import DeliveryError

BOT, CHAT = 123458, 424245
CONFIG = TransportConfiguration(
    BOT,
    f"{BOT}:" + "A" * 35,
    b"public-test-transport-vector-000000000000",
    "public-test-storage-vector-000000000000",
    "https://bank.invalid",
)
pytestmark = pytest.mark.integration


@pytest.fixture
async def delivery_db(seeded):
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await connect(dsn) as conn:
        for table in (
            "telegram_deliveries",
            "telegram_chat_rate",
            "telegram_signal_bindings",
            "telegram_client_bindings",
        ):
            await conn.execute(f"delete from channel_runtime.{table} where bot_id=%s", (BOT,))
    return dsn


async def connect(dsn):
    return await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row)


async def queued(dsn, *, chat=CHAT, run_id=None):
    async with await connect(dsn) as conn, conn.transaction():
        if run_id is None:
            run_id = (await (await conn.execute("select current_run_id from sim_state where id=1")).fetchone())[
                "current_run_id"
            ]
        return await enqueue_reply(
            conn, CONFIG, run_id=run_id, chat_id=chat, reply={"reply_text": "Synthetic bank response", "buttons": []}
        )


class Sender:
    def __init__(self, *, error=None, gate=None):
        self.calls = []
        self.error = error
        self.gate = gate
        self.entered = asyncio.Event()

    async def send(self, payload):
        self.calls.append(payload)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return "telegram:42"


async def statuses(dsn, nid):
    async with await connect(dsn) as conn:
        return await (
            await conn.execute(
                "select n.status,n.sent_sim,n.sent_at,n.external_ref,d.status as receipt,d.error_code from notifications n join channel_runtime.telegram_deliveries d on d.delivery_key=n.delivery_key where n.id=%s",
                (nid,),
            )
        ).fetchone()


async def test_admission_commits_before_http_and_parallel_worker_cannot_resend(delivery_db):
    nid = await queued(delivery_db)
    gate = asyncio.Event()
    sender = Sender(gate=gate)
    task = asyncio.create_task(deliver_once(CONFIG, sender, dsn=delivery_db))
    await asyncio.wait_for(sender.entered.wait(), 5)
    before = await statuses(delivery_db, nid)
    assert before["status"] == "queued" and before["receipt"] == "claimed"
    assert before["sent_at"] is None and before["external_ref"] is None
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    gate.set()
    assert await task is True
    result = await statuses(delivery_db, nid)
    assert result["status"] == result["receipt"] == "sent"
    assert result["external_ref"] == "telegram:42" and result["sent_at"] is not None and result["sent_sim"] is not None
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    assert len(sender.calls) == 1


async def test_per_chat_one_second_gate_does_not_delay_other_chat(delivery_db):
    first = await queued(delivery_db)
    second = await queued(delivery_db)
    other = await queued(delivery_db, chat=CHAT + 1)
    sender = Sender()
    assert await deliver_once(CONFIG, sender, dsn=delivery_db)
    assert await deliver_once(CONFIG, sender, dsn=delivery_db)
    assert (await statuses(delivery_db, second))["status"] == "queued"
    assert (await statuses(delivery_db, other))["status"] == "sent"
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    async with await connect(delivery_db) as conn:
        await conn.execute(
            "update channel_runtime.telegram_chat_rate set last_claimed_at=clock_timestamp()-interval '2 seconds' where bot_id=%s and chat_id=%s",
            (BOT, CHAT),
        )
    assert await deliver_once(CONFIG, sender, dsn=delivery_db)
    assert (await statuses(delivery_db, first))["status"] == "sent"
    assert (await statuses(delivery_db, second))["status"] == "sent"
    assert len(sender.calls) == 3


@pytest.mark.parametrize(
    "error,status",
    [
        (DeliveryError("rejected", "telegram_rejected_403"), "failed"),
        (DeliveryError("unknown", "telegram_transport_unknown"), "unknown"),
        (TimeoutError(), "unknown"),
    ],
)
async def test_failed_or_uncertain_send_is_explicit_and_never_automatically_retried(delivery_db, error, status):
    nid = await queued(delivery_db)
    sender = Sender(error=error)
    assert await deliver_once(CONFIG, sender, dsn=delivery_db)
    result = await statuses(delivery_db, nid)
    assert result["status"] == result["receipt"] == status
    assert result["external_ref"] is None and result["sent_at"] is None
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    assert len(sender.calls) == 1


async def test_cancelled_send_persists_unknown_and_preserves_retry_safety(delivery_db):
    nid = await queued(delivery_db)
    sender = Sender(gate=asyncio.Event())
    task = asyncio.create_task(deliver_once(CONFIG, sender, dsn=delivery_db))
    await asyncio.wait_for(sender.entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await statuses(delivery_db, nid))["status"] == "unknown"
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    assert len(sender.calls) == 1


async def test_abandoned_claim_becomes_unknown_without_send_and_restored_queued_state_reconciles(delivery_db):
    nid = await queued(delivery_db)
    async with await connect(delivery_db) as conn:
        await conn.execute(
            "update channel_runtime.telegram_deliveries set status='claimed',claimed_at=now() where bot_id=%s", (BOT,)
        )
    sender = Sender()
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    assert (await statuses(delivery_db, nid))["status"] == "unknown"
    async with await connect(delivery_db) as conn:
        await conn.execute("update notifications set status='queued' where id=%s", (nid,))
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    assert (await statuses(delivery_db, nid))["status"] == "unknown"
    assert sender.calls == []


async def test_sigkill_after_committed_claim_recovers_unknown_without_resend(delivery_db, tmp_path):
    nid = await queued(delivery_db)
    marker = tmp_path / "fake-wire-entered"
    root = Path(__file__).resolve().parents[3]
    # Отдельный owned process: fake wire не делает HTTP, но погибает как реальный worker.
    source = """
import asyncio, os
from pathlib import Path
from app.tgbot.configuration import TransportConfiguration
from app.tgbot.delivery import deliver_once
class FakeWire:
    async def send(self, payload):
        Path(os.environ['TEST_WIRE_MARKER']).write_text('entered')
        await asyncio.Event().wait()
config = TransportConfiguration(123458, '123458:' + 'A'*35,
    b'public-test-transport-vector-000000000000',
    'public-test-storage-vector-000000000000', 'https://bank.invalid')
asyncio.run(deliver_once(config, FakeWire(), dsn=os.environ['TEST_TG_DSN']))
"""
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": f"{root / 'backend'}:{root}",
        "ENV_FILE": "/dev/null",
        "APP_ENV": "test",
        "MAINTENANCE_CONTROL_DIR": os.environ["MAINTENANCE_CONTROL_DIR"],
        "TEST_TG_DSN": delivery_db,
        "TEST_WIRE_MARKER": str(marker),
    }
    child = subprocess.Popen(
        [sys.executable, "-c", source], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        async with asyncio.timeout(10):
            while not marker.exists():
                assert child.poll() is None, "fake worker exited before admission"
                await asyncio.sleep(0.02)
        assert (await statuses(delivery_db, nid))["receipt"] == "claimed"
        child.kill()
        assert await asyncio.to_thread(child.wait, 5) == -9
        sender = Sender()
        assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
        result = await statuses(delivery_db, nid)
        assert result["status"] == result["receipt"] == "unknown"
        assert result["error_code"] == "telegram_worker_interrupted"
        assert result["sent_at"] is None and result["external_ref"] is None
        assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
        assert sender.calls == []
    finally:
        if child.poll() is None:
            child.kill()
        await asyncio.to_thread(child.wait, 5)
        if child.stderr is not None:
            child.stderr.close()


async def test_inflight_delivery_holds_maintenance_and_run_delete_boundary(delivery_db):
    async with await connect(delivery_db) as conn:
        run = await (
            await conn.execute(
                "insert into sim_runs(kind,label,seed,status,started_sim) values('free','T121 outbound',42,'completed',now()) returning id"
            )
        ).fetchone()
    nid = await queued(delivery_db, run_id=run["id"])
    gate = asyncio.Event()
    sender = Sender(gate=gate)
    task = asyncio.create_task(deliver_once(CONFIG, sender, dsn=delivery_db))
    await asyncio.wait_for(sender.entered.wait(), 5)
    boundary = DatabaseBoundary(dsn=delivery_db, timeout_ms=100)
    try:
        with pytest.raises(MaintenanceBusy):
            await boundary.acquire()
        async with await connect(delivery_db) as conn:
            with pytest.raises(run_lifecycle.RunConflict, match="Telegram"):
                await run_lifecycle.delete(conn, run["id"])
    finally:
        gate.set()
        await task
        await boundary.release()
    assert (await statuses(delivery_db, nid))["status"] == "sent"
    await boundary.acquire()
    await boundary.release()
    async with await connect(delivery_db) as conn:
        await run_lifecycle.delete(conn, run["id"])
        assert (await (await conn.execute("select count(*) as n from notifications where id=%s", (nid,))).fetchone())[
            "n"
        ] == 0
        receipt = await (
            await conn.execute(
                "select status from channel_runtime.telegram_deliveries where notification_id=%s and bot_id=%s",
                (nid, BOT),
            )
        ).fetchone()
        assert receipt["status"] == "sent"


async def test_synthetic_seed_signal_has_no_delivery_grant_even_with_telegram_channel(delivery_db):
    async with await connect(delivery_db) as conn, conn.transaction():
        signal = await (
            await conn.execute(
                "select id,run_id,client_id from signals where channel_code='telegram_bot' order by id limit 1"
            )
        ).fetchone()
        assert signal is not None
        note = await (
            await conn.execute(
                "insert into notifications(run_id,recipient_type,signal_id,client_id,channel_code,template_code,body,status) values(%s,'client',%s,%s,'telegram_bot','ack_received','Synthetic seed response','queued') returning id",
                (signal["run_id"], signal["id"], signal["client_id"]),
            )
        ).fetchone()
        assert await enqueue_notification(conn, CONFIG, note["id"]) is False
    sender = Sender()
    assert await deliver_once(CONFIG, sender, dsn=delivery_db) is False
    async with await connect(delivery_db) as conn:
        assert (await (await conn.execute("select status from notifications where id=%s", (note["id"],))).fetchone())[
            "status"
        ] == "failed"
    assert sender.calls == []
