"""Даже резерв благодарности отвечает клиенту, а не возвращает название класса."""

import psycopg
import pytest

from tests.helpers import dsn, run_agent_on

pytestmark = pytest.mark.integration


async def test_mock_gratitude_is_a_polite_bank_reply_without_new_incident(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        sid, state = await run_agent_on(
            conn,
            "Спасибо сотрудникам банка за внимательное обслуживание! Мне подробно объяснили условия вклада. Всё понятно, вопросов больше нет.",
            client_id=cid,
        )
        assert state["classification"]["signal_type"] == "gratitude"
        assert state["decision"]["incident_action"] == "none"
        bodies = await (
            await conn.execute("select body from notifications where signal_id=%s and recipient_type='client'", (sid,))
        ).fetchall()
        assert len(bodies) == 1
        assert "Спасибо за тёплые слова" in bodies[0][0] and "Рады, что смогли помочь" in bodies[0][0]
        assert bodies[0][0] != "Благодарность"
        assert (
            await (await conn.execute("select count(*) from incident_signals where signal_id=%s", (sid,))).fetchone()
        )[0] == 0
