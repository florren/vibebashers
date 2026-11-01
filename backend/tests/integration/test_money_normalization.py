"""T-059: decimal hint проходит граф; возврат остаётся основан на ledger/rule, не тексте."""

from decimal import Decimal

import psycopg
import pytest

from app.abs.service import ensure_operation_posted
from app.agent.graph import process_signal
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration


async def test_decimal_normalization_preserves_rule_confirmed_fee_amount(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        row = await (
            await conn.execute(
                "select c.id from clients c where c.segment_code='mass' and c.is_active and exists (select 1 from client_products p where p.client_id=c.id and p.product_code='debit_card') and not exists (select 1 from operations o where o.client_id=c.id and o.error_code='PROC-QR-FEE-CHARGED') order by c.id limit 1"
            )
        ).fetchone()
        assert row is not None
        cid = row[0]
        rid = await new_run(conn, "decimal normalization boundary")
        now = await sim_now(conn)
        op = await (
            await conn.execute(
                "insert into operations(run_id,client_id,product_code,op_type,system_path,amount_rub,method,merchant,fee_amount,status,error_code,started_sim,finished_sim) values(%s,%s,'debit_card','card_payment',array['processing','core_abs'],%s,'qr_sbp','Тестовый магазин',%s,'failed','PROC-QR-FEE-CHARGED',%s,%s) returning id",
                (rid, cid, Decimal("5472.45"), Decimal("54.72"), now, now),
            )
        ).fetchone()
        op_id = op[0]
        await ensure_operation_posted(conn, op_id)
        await conn.commit()
        accepted = await create_signal(
            conn,
            from_api_signal(
                {
                    "channel_code": "chat",
                    "client_id": cid,
                    "text": "Оплатил по QR 5472.45 рублей, а с карты списали комиссию54.72руб. СБП же бесплатно! Верните комиссию.",
                }
            ),
            source_code="api",
            run_id=rid,
            sim_time=now,
            emit_event=False,
        )
        await conn.commit()
        state = await process_signal(
            conn, signal_id=int(accepted["signal_id"]), chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
        )
        assert state is not None
        assert state["errors"] == []
        assert state["normalization"]["entities"]["amount_rub"] == 5472.45
        assert state["context"]["fast_path"]["allowed"] is True, state["context"]["fast_path"]
        assert state["outcome"] == "completed"
        fees = await (
            await conn.execute(
                "select kind,amount from ledger_entries where operation_id=%s and kind in ('fee','refund') order by kind",
                (op_id,),
            )
        ).fetchall()
        assert fees == [("fee", Decimal("54.72")), ("refund", Decimal("54.72"))]
        assert (
            await (
                await conn.execute(
                    "select count(*) from human_decisions where agent_run_id=%s", (state["agent_run_id"],)
                )
            ).fetchone()
        )[0] == 0
