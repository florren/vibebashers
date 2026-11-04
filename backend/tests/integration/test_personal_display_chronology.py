"""Personal history must display delivery time, not the writer transaction start."""

import asyncio
import datetime as dt
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent.tools.base import ToolContext
from app.agent.tools.write import notify_client
from app.config import get_settings
from app.public_chat import create_public_app
from tests.helpers import dsn


@pytest.mark.parametrize("channel", ["chat", "email", "sms", "push", "landing", "telegram_bot"])
def test_personal_answer_timestamp_follows_question_from_newer_transaction(seeded, conn, monkeypatch, channel):
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("TGBOT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_public_app())
        boot = client.get("/api/personal/session").json()
        conn.execute("update personal_chat_sessions set created_at=now()-interval '3 seconds'")

        async def deliver():
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as older:
                started = (await (await older.execute("select now()")).fetchone())[0]
                accepted = client.post(
                    "/api/personal/messages",
                    json={
                        "text": "Почему не открывается вклад?",
                        "request_id": str(uuid.uuid4()),
                        "form_token": boot["form_token"],
                    },
                )
                assert accepted.status_code == 202, accepted.text
                signal, run, at, received = await (
                    await older.execute(
                        "select id,run_id,received_sim,received_at from signals where public_id=%s",
                        (accepted.json()["public_id"],),
                    )
                ).fetchone()
                assert received > started
                ctx = ToolContext(older, run_id=run, agent_run_id=0, sim_time=at)
                note = await notify_client(ctx, None, signal, None, channel, "ack_received", {"text": "Ответ банка"})
                created, sent = await (
                    await older.execute(
                        "select created_at,sent_at from notifications where id=%s",
                        (note["notification_id"],),
                    )
                ).fetchone()
                assert created == started and sent >= received
                await older.commit()
                return received, sent

        received, sent = asyncio.run(deliver())
        for status in ("queued", "failed", "unknown", "suppressed"):
            conn.execute(
                "insert into notifications(run_id,signal_id,recipient_type,channel_code,body,status) "
                "select s.run_id,s.id,'client','chat','Not delivered',%s "
                "from signals s join personal_chat_messages m on m.signal_id=s.id",
                (status,),
            )
        response = client.get("/api/personal/messages")
        assert response.status_code == 200
        history = response.json()
        assert len(history["messages"]) == 1 and len(history["answers"]) == 1
        answer = dt.datetime.fromisoformat(history["answers"][0]["at"])
        assert answer == sent
        assert answer >= received
        legacy_id, legacy_at = conn.execute(
            "insert into notifications(run_id,signal_id,recipient_type,channel_code,body,status) "
            "select s.run_id,s.id,'client','chat','Legacy delivered','delivered' "
            "from signals s join personal_chat_messages m on m.signal_id=s.id returning id,created_at"
        ).fetchone()
        legacy = next(a for a in client.get("/api/personal/messages").json()["answers"] if a["id"] == legacy_id)
        assert dt.datetime.fromisoformat(legacy["at"]) == legacy_at
    finally:
        get_settings.cache_clear()
