"""Только собственная scratch БД: durable receipts до включения production route."""

from __future__ import annotations

import asyncio
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.tgbot.storage import InboundStore, ReceiptConflict

ROOT = Path(__file__).resolve().parents[3]
SECRET = "public-test-storage-vector-000000000000"
BODY = b'{"update_id":71,"chat_id":9002}'
BOT, CHAT = 9001, 9002
pytestmark = pytest.mark.integration


@pytest.fixture
async def store_db(migrated_db):
    dsn = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        sql = (ROOT / "contracts/db/migrations/0015_telegram_transport.sql").read_text()
        await conn.execute(sql)
        await conn.execute(sql)
        for table in ("telegram_conversations", "telegram_inbound"):
            await conn.execute(f"delete from channel_runtime.{table} where bot_id = %s", (BOT,))
    return dsn


async def connect(dsn):
    return await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row)


async def test_new_store_after_connection_close_reads_encrypted_draft_and_receipt(store_db):
    async with await connect(store_db) as conn:
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
            assert not turn.duplicate
            turn.state["text"] = "synthetic private draft"
            turn.response = {"accepted": True, "update_id": 71}
    # Новый объект и connection: в памяти transport ничего не сохраняется.
    async with await connect(store_db) as conn:
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
            assert turn.duplicate and turn.response == {"accepted": True, "update_id": 71}
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=72, chat_id=CHAT, body=b"next") as turn:
            assert turn.state["text"] == "synthetic private draft"
            turn.response = {"accepted": True, "update_id": 72}
        row = await (
            await conn.execute("select state_enc from channel_runtime.telegram_conversations where bot_id = %s", (BOT,))
        ).fetchone()
        assert b"synthetic private draft" not in bytes(row["state_enc"])


async def test_failed_handler_rolls_back_state_receipt_and_its_side_effect(store_db):
    async with await connect(store_db) as conn:
        await conn.execute("create temporary table own_turn_effect(value integer)")
        with pytest.raises(RuntimeError, match="injected"):
            async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
                await conn.execute("insert into own_turn_effect values(1)")
                turn.state["stage"] = "region"
                turn.response = {"accepted": True}
                raise RuntimeError("injected")
        assert (await (await conn.execute("select count(*) as n from own_turn_effect")).fetchone())["n"] == 0
        for table in ("telegram_conversations", "telegram_inbound"):
            assert (
                await (
                    await conn.execute(f"select count(*) as n from channel_runtime.{table} where bot_id=%s", (BOT,))
                ).fetchone()
            )["n"] == 0
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
            assert not turn.duplicate and turn.state["stage"] == "role"
            turn.response = {"accepted": True}


async def test_parallel_duplicate_executes_dialog_handler_once(store_db):
    entered = []

    async def submit():
        async with await connect(store_db) as conn:
            async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
                if not turn.duplicate:
                    entered.append(1)
                    turn.state["turns"] = 1
                    turn.response = {"accepted": True, "update_id": 71}
                return turn.response

    result = await asyncio.gather(submit(), submit(), submit())
    assert entered == [1] and result == [{"accepted": True, "update_id": 71}] * 3


async def test_duplicate_with_different_body_or_chat_fails_without_second_receipt(store_db):
    async with await connect(store_db) as conn:
        store = InboundStore(SECRET)
        async with store.turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
            turn.response = {"accepted": True}
        for chat, body in ((CHAT, b"changed"), (CHAT + 1, BODY)):
            with pytest.raises(ReceiptConflict):
                async with store.turn(conn, bot_id=BOT, update_id=71, chat_id=chat, body=body):
                    pytest.fail("conflicting receipt reached handler")
        assert (
            await (
                await conn.execute("select count(*) as n from channel_runtime.telegram_inbound where bot_id=%s", (BOT,))
            ).fetchone()
        )["n"] == 1


async def test_missing_response_rolls_back_and_next_update_preserves_state(store_db):
    async with await connect(store_db) as conn:
        with pytest.raises(ValueError, match="response_missing"):
            async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
                turn.state["stage"] = "region"
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=72, chat_id=CHAT, body=b"next") as turn:
            assert turn.state["stage"] == "role"
            turn.response = {"accepted": True}


async def test_bank_dump_restore_keeps_newer_operational_receipt_and_notification_identity(store_db, tmp_path):
    import subprocess

    from app.sim import baseline

    archive = tmp_path / "owned-bank.dump"
    async with await connect(store_db) as conn:
        run = await (
            await conn.execute(
                "insert into sim_runs(kind,label,seed,status,started_sim) values('baseline','T121 scratch',42,'completed',now()) returning id"
            )
        ).fetchone()
        note = await (
            await conn.execute(
                "insert into notifications(run_id,recipient_type,channel_code,body) values(%s,'client','telegram_bot','synthetic') returning id,delivery_key",
                (run["id"],),
            )
        ).fetchone()
        await conn.execute(
            "insert into channel_runtime.telegram_deliveries(delivery_key,bot_id,chat_id,notification_id,run_id,body_hash,payload_enc,status,completed_at,external_ref) "
            "values(%s,%s,%s,%s,%s,%s,pgp_sym_encrypt('{}',%s),'sent',now(),'telegram:42')",
            (note["delivery_key"], BOT, CHAT, note["id"], run["id"], "a" * 64, SECRET),
        )
    await asyncio.to_thread(baseline._run_pg_dump, store_db, archive)
    listing = subprocess.run(
        [baseline._pg_tool("pg_restore"), "--list", str(archive)], capture_output=True, text=True, check=True
    ).stdout
    assert "channel_runtime" not in listing
    async with await connect(store_db) as conn:
        await conn.execute("delete from notifications where id=%s", (note["id"],))
        reused = await (
            await conn.execute(
                "insert into notifications(id,run_id,recipient_type,channel_code,body) overriding system value values(%s,%s,'client','telegram_bot','new synthetic') returning delivery_key",
                (note["id"], run["id"]),
            )
        ).fetchone()
        assert reused["delivery_key"] != note["delivery_key"]
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
            turn.state["after_dump"] = True
            turn.response = {"accepted": True, "update_id": 71}
        ciphertext = await (
            await conn.execute("select state_enc from channel_runtime.telegram_conversations where bot_id=%s", (BOT,))
        ).fetchone()
    await asyncio.to_thread(baseline._run_pg_restore, store_db, archive)
    async with await connect(store_db) as conn:
        restored = await (
            await conn.execute("select delivery_key from notifications where id=%s", (note["id"],))
        ).fetchone()
        assert restored["delivery_key"] == note["delivery_key"]
        current = await (
            await conn.execute("select state_enc from channel_runtime.telegram_conversations where bot_id=%s", (BOT,))
        ).fetchone()
        assert current["state_enc"] == ciphertext["state_enc"]
        async with InboundStore(SECRET).turn(conn, bot_id=BOT, update_id=71, chat_id=CHAT, body=BODY) as turn:
            assert turn.duplicate and turn.response["update_id"] == 71
        delivery = await (
            await conn.execute(
                "select status,external_ref from channel_runtime.telegram_deliveries where delivery_key=%s",
                (note["delivery_key"],),
            )
        ).fetchone()
        assert delivery == {"status": "sent", "external_ref": "telegram:42"}
        no_foreign_keys = await (
            await conn.execute(
                "select count(*) as n from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='channel_runtime' and c.contype='f'"
            )
        ).fetchone()
        assert no_foreign_keys["n"] == 0
