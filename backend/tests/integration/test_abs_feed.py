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
        original_balances = dict(await (await conn.execute("select id,balance from accounts")).fetchall())
        first = await abs_svc.backfill_ledger(conn)
        second = await abs_svc.backfill_ledger(conn)
        await conn.commit()
        assert first["debits"] >= 0 and second == {"debits": 0, "fees": 0, "credits": 0}
        assert await abs_svc.check_invariant(conn) == []
        balances = dict(await (await conn.execute("select id,balance from accounts")).fetchall())
        assert all(balances[account_id] == balance for account_id, balance in original_balances.items())
        # Знак opening определяется исходным остатком минус движением, а не итоговым балансом.
        for account_id, balance in original_balances.items():
            net, count = await (
                await conn.execute(
                    "select coalesce(sum(case when kind in ('credit','refund') then amount else -amount end),0),count(*) "
                    "from ledger_entries where account_id=%s and operation_id is not null",
                    (account_id,),
                )
            ).fetchone()
            opening = await (
                await conn.execute(
                    "select kind,amount from ledger_entries where account_id=%s and operation_id is null", (account_id,)
                )
            ).fetchall()
            if balance != 0 or count:
                expected = balance - net
                assert opening == [("credit" if expected >= 0 else "debit", abs(expected))]
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


async def _opening_case(conn, balance, spent):
    from decimal import Decimal

    run = await new_run(conn, "ABS opening QA")
    client = (
        await (
            await conn.execute(
                "insert into clients(display_name,segment_code,psychotype_code,region_code,city_id,clv_estimate_rub) "
                "select 'ABS QA',segment_code,psychotype_code,region_code,city_id,clv_estimate_rub from clients order by id limit 1 returning id"
            )
        ).fetchone()
    )[0]
    account = (
        await (
            await conn.execute(
                "insert into accounts(client_id,number_masked,currency,balance,status) values(%s,'QA ****','RUB',%s,'active') returning id",
                (client, Decimal(str(balance))),
            )
        ).fetchone()
    )[0]
    operation = None
    if spent:
        operation = (
            await (
                await conn.execute(
                    "insert into operations(run_id,client_id,product_code,op_type,system_path,amount_rub,fee_amount,status,started_sim) "
                    "values(%s,%s,'deposit','deposit_open',ARRAY['core_abs'],%s,0,'success',%s) returning id",
                    (run, client, Decimal(str(spent)), await sim_now(conn)),
                )
            ).fetchone()
        )[0]
    return run, client, account, operation


@pytest.mark.parametrize(
    "balance,spent", [(-3400, 0), (-3400, 1000), (-3400, 3400), (-3400, 5000), (0, 100), (1200, 100), (0, 0), (1200, 0)]
)
async def test_backfill_preserves_signed_opening_balance_and_repeat(seeded, balance, spent):
    from decimal import Decimal

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        _run, _client, account, _operation = await _opening_case(conn, balance, spent)
        before = dict(await (await conn.execute("select id,balance from accounts")).fetchall())
        await abs_svc.backfill_ledger(conn)
        after = dict(await (await conn.execute("select id,balance from accounts")).fetchall())
        assert all(after[account_id] == value for account_id, value in before.items())
        opening = await (
            await conn.execute(
                "select kind,amount from ledger_entries where account_id=%s and operation_id is null", (account,)
            )
        ).fetchall()
        expected = Decimal(str(balance + spent))
        assert opening == ([("credit" if expected >= 0 else "debit", abs(expected))] if balance or spent else [])
        assert await abs_svc.check_invariant(conn) == []
        assert await abs_svc.backfill_ledger(conn) == {"debits": 0, "fees": 0, "credits": 0}
        assert dict(await (await conn.execute("select id,balance from accounts")).fetchall()) == after


async def test_backfill_opening_accounts_for_existing_refund_without_creating_refund(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, account, operation = await _opening_case(conn, 200, 100)
        await conn.execute("update operations set fee_amount=20 where id=%s", (operation,))
        now = await sim_now(conn)
        await abs_svc.post_entry(
            conn,
            run_id=run,
            client_id=client,
            kind="debit",
            amount=100,
            correlation_id=uuid.uuid4(),
            posted_sim=now,
            operation_id=operation,
            emit=False,
        )
        fee = await abs_svc.post_entry(
            conn,
            run_id=run,
            client_id=client,
            kind="fee",
            amount=20,
            correlation_id=uuid.uuid4(),
            posted_sim=now,
            operation_id=operation,
            emit=False,
        )
        await abs_svc.post_entry(
            conn,
            run_id=run,
            client_id=client,
            kind="refund",
            amount=20,
            correlation_id=uuid.uuid4(),
            posted_sim=now,
            operation_id=operation,
            refund_of_entry_id=fee["entry_id"],
            emit=False,
        )
        assert (await (await conn.execute("select balance from accounts where id=%s", (account,))).fetchone())[0] == 100
        refunds = await (
            await conn.execute("select to_jsonb(l) from ledger_entries l where kind='refund' order by id")
        ).fetchall()
        await abs_svc.backfill_ledger(conn)
        assert (await (await conn.execute("select balance from accounts where id=%s", (account,))).fetchone())[0] == 100
        assert (
            await (
                await conn.execute(
                    "select kind,amount from ledger_entries where account_id=%s and operation_id is null", (account,)
                )
            ).fetchone()
        ) == ("credit", 200)
        assert (
            await (
                await conn.execute("select to_jsonb(l) from ledger_entries l where kind='refund' order by id")
            ).fetchall()
            == refunds
        )
        assert await abs_svc.backfill_ledger(conn) == {"debits": 0, "fees": 0, "credits": 0}


async def test_backfill_scope_preserves_other_operations_and_existing_opening(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, account, operation = await _opening_case(conn, 0, 20)
        _foreign_run, _foreign_client, _foreign_account, foreign_operation = await _opening_case(conn, 10, 30)
        initial = await abs_svc.post_entry(
            conn,
            run_id=run,
            client_id=client,
            kind="credit",
            amount=100,
            correlation_id=uuid.uuid4(),
            posted_sim=await sim_now(conn),
            emit=False,
        )
        marker = await (
            await conn.execute("select to_jsonb(l) from ledger_entries l where id=%s", (initial["entry_id"],))
        ).fetchone()
        await abs_svc.backfill_ledger(conn, run_id=run)
        assert (await (await conn.execute("select balance from accounts where id=%s", (account,))).fetchone())[0] == 80
        assert (
            await (
                await conn.execute("select count(*) from ledger_entries where operation_id=%s", (operation,))
            ).fetchone()
        )[0] == 1
        assert (
            await (
                await conn.execute("select count(*) from ledger_entries where operation_id=%s", (foreign_operation,))
            ).fetchone()
        )[0] == 0
        assert (
            await (
                await conn.execute("select to_jsonb(l) from ledger_entries l where id=%s", (initial["entry_id"],))
            ).fetchone()
            == marker
        )
        assert await abs_svc.backfill_ledger(conn, run_id=run) == {"debits": 0, "fees": 0, "credits": 0}
