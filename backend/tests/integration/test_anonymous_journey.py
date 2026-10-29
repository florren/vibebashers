"""Анонимный вход не блокирует классификацию, маршрут и подтверждение приёма."""

from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row

from app.economics.dcltv import compute_incident
from app.trace.journey import journey
from tests.helpers import dsn, new_run, run_agent_on

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "text",
    [
        "Не проходит оплата дебетовой картой, приложение показывает ошибку. Разберитесь.",
        "Всё не работает, разберитесь с моим обращением.",
        "Отказали в кредитной карте без объяснений. Почему?",
    ],
)
async def test_anonymous_handoff_and_recorded_ack(seeded, text):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "anonymous handoff")
        signal_id, state = await run_agent_on(conn, text, client_id=None, run_id=rid)
        await conn.commit()
        assert state["classification"]["signal_type"]
        decision = state["decision"]
        assert decision["router_action"] in ("route", "escalate")
        assert not decision["clarification_question_ru"]
        assert decision["incident_action"] in ("create", "link_existing")
        incident = await (
            await conn.execute(
                "SELECT i.id, i.team_code, i.product_code, i.primary_client_id FROM incidents i JOIN incident_signals s ON s.incident_id=i.id WHERE s.signal_id=%s",
                (signal_id,),
            )
        ).fetchone()
        assert incident and incident[3] is None
        assert incident[1] == decision["route"]["team"]
        ack = await (
            await conn.execute(
                "SELECT body, status FROM notifications WHERE signal_id=%s AND recipient_type='client'", (signal_id,)
            )
        ).fetchall()
        assert len(ack) == 1 and ack[0][1] == "sent"
        assert "О решении сообщим дополнительно" in ack[0][0]
        assert not any(word in ack[0][0].lower() for word in ("телефон", "паспорт", "уточните", "номер карты"))
        losses = await compute_incident(conn, incident[0])
        assert losses
        if not incident[2]:
            assert losses["rate_code"] == "bank_average"
            assert losses["potential_loss_rub"] > 0
        assert (
            await (
                await conn.execute("SELECT count(*) FROM ledger_entries WHERE run_id=%s AND created_by='agent'", (rid,))
            ).fetchone()
        )[0] == 0
        await conn.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")
        model = await journey(conn, f"SIG-{signal_id:06d}", str(rid))
        assert any("О решении сообщим дополнительно" in message["text_ru"] for message in model["client_lane"])
