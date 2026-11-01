"""Financial regression: чужая QR-комиссия не решает текущую проблему клиента."""

from decimal import Decimal

import psycopg
import pytest

from app.abs.service import ensure_operation_posted
from app.agent.graph import process_signal
from app.agent.tools.abs import find_affected_clients
from app.agent.tools.base import ToolContext
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration


async def setup(conn):
    rid = await new_run(conn, "refund case relevance")
    cid = (
        await (
            await conn.execute(
                "select c.id from clients c where c.segment_code='mass' and exists (select 1 from client_products p where p.client_id=c.id and p.product_code='debit_card') order by c.id limit 1"
            )
        ).fetchone()
    )[0]
    now = await sim_now(conn)
    return rid, cid, now


async def qr(conn, rid, cid, now, amount="3200", fee="54.72"):
    op = (
        await (
            await conn.execute(
                "insert into operations(run_id,client_id,product_code,op_type,system_path,amount_rub,method,merchant,fee_amount,status,error_code,started_sim,finished_sim) values(%s,%s,'debit_card','card_payment',array['processing','core_abs'],%s,'qr_sbp','Тестовый магазин',%s,'failed','PROC-QR-FEE-CHARGED',%s,%s) returning id",
                (rid, cid, Decimal(amount), Decimal(fee), now, now),
            )
        ).fetchone()
    )[0]
    await ensure_operation_posted(conn, op)
    await conn.commit()
    return op


async def run(conn, rid, cid, now, text, channel="chat", origin="jury"):
    accepted = await create_signal(
        conn,
        from_api_signal({"channel_code": channel, "client_id": cid, "text": text}, origin=origin),
        source_code="api",
        run_id=rid,
        sim_time=now,
        emit_event=False,
    )
    assert accepted["status"] == "accepted", accepted
    await conn.commit()
    state = await process_signal(
        conn, signal_id=int(accepted["signal_id"]), chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
    )
    assert state is not None and not state["errors"]
    return int(accepted["signal_id"]), state


async def count(conn, query, args=()):
    return (await (await conn.execute(query, args)).fetchone())[0]


@pytest.mark.parametrize(
    "text",
    [
        "Не открывается вклад в мобильном приложении, ошибка503",
        "Спасибо за удобную оплату по QR!",
        "QR, ну ок",
        "Оплата QR не проходит, приложение падает",
        "Не узнаю списание3200по дебетовой карте, верните деньги",
        "Не я совершал покупку3200по дебетовой карте, подозреваю мошенничество. Верните деньги",
    ],
)
async def test_other_claim_never_refunds_or_issues_gift_for_existing_qr_fee(seeded, text):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid, cid, now = await setup(conn)
        op = await qr(conn, rid, cid, now)
        balance = await count(conn, "select balance from accounts where client_id=%s", (cid,))
        sid, state = await run(conn, rid, cid, now, text)
        assert any(o["operation_id"] == op for o in state["context"]["operations"]), (
            "QR fixture должна оставаться в полном CRM context"
        )
        assert not state["context"]["fast_path"]["allowed"]
        assert not any(r["action"] == "refund_fee" for r in state["context"]["rules_matched"])
        assert (
            await count(
                conn,
                "select count(*) from rule_evaluations where agent_run_id=%s and result='matched' and proposed_action='refund_fee'",
                (state["agent_run_id"],),
            )
            == 0
        )
        assert (
            await count(conn, "select count(*) from ledger_entries where operation_id=%s and kind='refund'", (op,)) == 0
        )
        assert await count(conn, "select balance from accounts where client_id=%s", (cid,)) == balance
        assert (
            await count(
                conn, "select count(*) from tasks where run_id=%s and kind='gift' and payload ? 'issued'", (rid,)
            )
            == 0
        )
        assert (
            await count(conn, "select count(*) from incidents where run_id=%s and incident_type='fee_refund'", (rid,))
            == 0
        )
        if "вклад" in text:
            assert state["classification"]["product"] == "deposit"
            assert (
                await count(
                    conn,
                    "select count(*) from incidents i join incident_signals s on s.incident_id=i.id where s.signal_id=%s and i.status in ('resolved','closed')",
                    (sid,),
                )
                == 0
            )
        if "мошенничество" in text:
            assert state["classification"]["signal_type"] == "fraud_suspicion"


async def test_qr_decimal_claim_refunds_only_matching_operation(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid, cid, now = await setup(conn)
        intended = await qr(conn, rid, cid, now, "5472.45", "54.72")
        unrelated = await qr(conn, rid, cid, now, "9000", "90")
        _sid, state = await run(
            conn, rid, cid, now, "Оплатил по QR5472.45руб, списали комиссию54.72руб. Верните комиссию"
        )
        assert state["normalization"]["entities"]["amount_rub"] == 5472.45
        assert state["context"]["fast_path"]["allowed"] and state["outcome"] == "completed"
        rule = next(r for r in state["context"]["rules_matched"] if r["action"] == "refund_fee")
        assert rule["operation_ids"] == [intended]
        assert await count(
            conn, "select sum(amount) from ledger_entries where operation_id=%s and kind='refund'", (intended,)
        ) == Decimal("54.72")
        assert (
            await count(
                conn, "select count(*) from ledger_entries where operation_id=%s and kind='refund'", (unrelated,)
            )
            == 0
        )


async def test_ambiguous_fee_claim_does_not_choose_or_refund_all_operations(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid, cid, now = await setup(conn)
        await qr(conn, rid, cid, now, "3200", "54.72")
        await qr(conn, rid, cid, now, "4000", "54.72")
        _sid, state = await run(conn, rid, cid, now, "По QR списали комиссию54.72руб. Верните комиссию")
        assert not state["context"]["fast_path"]["allowed"]
        assert not any(r["action"] == "refund_fee" for r in state["context"]["rules_matched"])
        assert await count(conn, "select count(*) from ledger_entries where run_id=%s and kind='refund'", (rid,)) == 0


async def test_explicit_proactive_fee_case_does_not_close_existing_deposit_claim(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid, cid, now = await setup(conn)
        op = await qr(conn, rid, cid, now)
        sid, _deposit = await run(conn, rid, cid, now, "Не открывается вклад в мобильном приложении, ошибка503")
        iid = await count(conn, "select incident_id from incident_signals where signal_id=%s", (sid,))
        before = await count(conn, "select status from incidents where id=%s", (iid,))
        _fee_sid, state = await run(
            conn,
            rid,
            cid,
            now,
            "Обнаружена ошибочно списанная комиссия54.72руб за QR оплату3200руб.",
            channel="proactive",
            origin="proactive",
        )
        assert state["context"]["fast_path"]["allowed"] and state["outcome"] == "completed"
        assert await count(
            conn, "select sum(amount) from ledger_entries where operation_id=%s and kind='refund'", (op,)
        ) == Decimal("54.72")
        assert await count(conn, "select status from incidents where id=%s", (iid,)) == before
        assert await count(conn, "select count(*) from tasks where incident_id=%s and payload ? 'issued'", (iid,)) == 0


async def test_mass_scan_remains_separate_from_individual_case_scope(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid, cid, now = await setup(conn)
        op = await qr(conn, rid, cid, now)
        other = (
            await (await conn.execute("select id from clients where id<>%s order by id limit 1", (cid,))).fetchone()
        )[0]
        second = await qr(conn, rid, other, now, "7000", "70")
        _sid, state = await run(conn, rid, cid, now, "Списали комиссию54.72руб за QR. Верните комиссию")
        assert state["context"]["fast_path"]["allowed"]
        ctx = ToolContext(conn, run_id=rid, agent_run_id=state["agent_run_id"], sim_time=now)
        affected = await find_affected_clients(ctx, "PROC-QR-FEE-CHARGED", 72)
        assert affected["pending_count"] == 1 and affected["operations"][0]["operation_id"] == second
        assert (
            await count(conn, "select count(*) from ledger_entries where operation_id=%s and kind='refund'", (second,))
            == 0
        )
        assert (
            await count(conn, "select count(*) from ledger_entries where operation_id=%s and kind='refund'", (op,)) == 1
        )




@pytest.mark.parametrize("stale", [True, False])
async def test_checkpoint_scope_preserves_human_decision_and_normal_approved_refund(seeded, stale):
    from psycopg.types.json import Jsonb

    from app.agent.graph import resume_after_human

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid, cid, now = await setup(conn)
        op = await qr(conn, rid, cid, now, "3200", "6000")
        sid, state = await run(
            conn, rid, cid, now, "Ошибочно списали комиссию6000руб за QR оплату3200руб. Верните комиссию"
        )
        assert state["outcome"] == "awaiting_human"
        hid = await count(conn, "select id from human_decisions where agent_run_id=%s", (state["agent_run_id"],))
        if stale:
            row = await (
                await conn.execute(
                    "select id,input from agent_steps where run_id=%s and node='wait_human' order by seq desc limit 1",
                    (state["agent_run_id"],),
                )
            ).fetchone()
            checkpoint = row[1]
            checkpoint["signal"]["text"] = "Не открывается вклад в приложении, ошибка503"
            checkpoint["normalization"]["intents"] = ["complaint"]
            checkpoint["normalization"]["entities"] = {"product": "deposit", "operation_hint": "deposit"}
            await conn.execute("update agent_steps set input=%s where id=%s", (Jsonb(checkpoint), row[0]))
            await conn.execute("update signals set text=%s where id=%s", (checkpoint["signal"]["text"], sid))
        await conn.execute(
            "update human_decisions set decision='accept',decided_by='test',decided_at=now() where id=%s", (hid,)
        )
        await conn.commit()
        resumed = await resume_after_human(
            conn, human_decision_id=hid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
        )
        assert resumed is not None
        assert await count(conn, "select decision from human_decisions where id=%s", (hid,)) == "accept"
        if stale:
            assert resumed["outcome"] == "failed" and any("stale_refund_scope" in error for error in resumed["errors"])
            assert (
                await count(conn, "select count(*) from ledger_entries where operation_id=%s and kind='refund'", (op,))
                == 0
            )
            assert (
                await count(conn, "select count(*) from incidents where agent_run_id=%s", (state["agent_run_id"],)) == 0
            )
            assert await count(conn, "select count(*) from tasks where run_id=%s and payload ? 'issued'", (rid,)) == 0
        else:
            assert resumed["outcome"] != "failed", resumed["errors"]
            assert await count(
                conn, "select sum(amount) from ledger_entries where operation_id=%s and kind='refund'", (op,)
            ) == Decimal("6000")
            await resume_after_human(
                conn, human_decision_id=hid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
            )
            assert (
                await count(conn, "select count(*) from ledger_entries where operation_id=%s and kind='refund'", (op,))
                == 1
            )
