"""B06/B16: Mock-АБС (инвариант баланса, идемпотентный возврат, отказ без правила) и публичная лента (пост → ответ, санитизация ПДн)."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from app.abs import service as abs_svc
from app.feed import service as feed_svc
from app.sim import runs as run_svc
from tests.helpers import dsn, new_run, sim_now

pytestmark = pytest.mark.integration


async def _client_with_qr_fee(conn: psycopg.AsyncConnection) -> tuple[int, int]:
    row = await (
        await conn.execute(
            "select id, client_id from operations where error_code = 'PROC-QR-FEE-CHARGED' and fee_amount > 0 order by id limit 1"
        )
    ).fetchone()
    assert row, "в сиде нет операции с ошибочной комиссией за QR"
    return int(row[0]), int(row[1])


async def test_backfill_invariant_and_idempotent(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        first = await abs_svc.backfill_ledger(conn)
        second = await abs_svc.backfill_ledger(conn)
        await conn.commit()
        assert first["debits"] >= 0 and second == {"debits": 0, "fees": 0, "credits": 0}
        assert await abs_svc.check_invariant(conn) == []
        row = await (
            await conn.execute(
                "select count(*) from accounts a where a.balance < 0 and not exists "
                "(select 1 from ledger_entries l where l.account_id = a.id and l.operation_id is null and l.kind = 'debit')"
            )
        ).fetchone()
        assert row and int(row[0]) == 0, "отрицательный баланс допустим только как задолженность из сида"
        for _ in range(3):  # повторные запуски ничего не добавляют
            assert await abs_svc.backfill_ledger(conn) == {"debits": 0, "fees": 0, "credits": 0}


async def test_refund_requires_rule_and_is_idempotent(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        await abs_svc.backfill_ledger(conn)
        run_id = await new_run(conn, "test abs refund")
        now = await sim_now(conn)
        op_id, client_id = await _client_with_qr_fee(conn)
        acc = await abs_svc.ensure_account(conn, client_id)
        with pytest.raises(abs_svc.AbsError):  # агент: правило не подтверждено → отказ без побочных эффектов
            await abs_svc.refund_fee(
                conn,
                run_id=run_id,
                operation_id=op_id,
                amount_rub=None,
                rule_id="RULE-QR-FEE-001",
                reason="t",
                posted_sim=now,
            )
        res = await abs_svc.refund_fee(
            conn,
            run_id=run_id,
            operation_id=op_id,
            amount_rub=None,
            rule_id=None,
            reason="решение человека",
            posted_sim=now,
            created_by="human",
            require_rule=False,
        )
        assert res["duplicate"] is False and res["amount_rub"] > 0
        assert abs(res["balance_after"] - (acc["balance"] + res["amount_rub"])) < 0.005
        again = await abs_svc.refund_fee(
            conn,
            run_id=run_id,
            operation_id=op_id,
            amount_rub=None,
            rule_id=None,
            reason="повтор",
            posted_sim=now,
            require_rule=False,
        )
        assert again["duplicate"] is True and again["entry_id"] == res["entry_id"]
        with pytest.raises(abs_svc.AbsError):  # сумма больше комиссии
            await abs_svc.post_entry(
                conn,
                run_id=run_id,
                client_id=client_id,
                kind="refund",
                amount=-1,
                correlation_id=uuid.uuid4(),
                posted_sim=now,
            )
        assert await abs_svc.check_invariant(conn) == []
        await run_svc.set_run_status(conn, run_id, "completed", now)  # не оставляем running-запуск другим тестам
        await conn.commit()


async def test_feed_post_reply_sanitized(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "test feed")
        now = await sim_now(conn)
        post = await feed_svc.create_post(
            conn,
            run_id=run_id,
            platform="review_portal",
            author_nick="angry_user",
            text="Списали комиссию 450 ₽ за QR, верните!",
            posted_sim=now,
        )
        assert post["public_id"].startswith("POST-")
        rep = await feed_svc.publish_reply(
            conn,
            run_id=run_id,
            post_id=post["post_id"],
            text="Иван, карта 1234 5678 9012 3456 и телефон +7 912 345-67-89: гарантируем возврат в течение 5 минут.",
            author="agent",
            sim_time=now,
            agent_run_id=None,
        )
        assert "3456" not in rep["text"] and "+7" not in rep["text"] and "гарантируем" not in rep["text"]
        assert rep["status"] == "replied" and rep["latency_ms"] >= 0
        dup = await feed_svc.publish_reply(
            conn,
            run_id=run_id,
            post_id=post["post_id"],
            text="ещё раз",
            author="agent",
            sim_time=now,
            agent_run_id=None,
        )
        assert dup["duplicate"] is True
        await conn.commit()
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as dconn:
            stats = await feed_svc.feed_stats(dconn, run_id)
        assert stats["posts"] == 1 and stats["replied"] == 1
        with pytest.raises(feed_svc.FeedError):
            await feed_svc.publish_reply(
                conn, run_id=run_id, post_id=999_999, text="нет поста", author="human", sim_time=now
            )
        await run_svc.set_run_status(conn, run_id, "completed", now)
        await conn.commit()
