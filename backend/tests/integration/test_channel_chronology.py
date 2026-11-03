"""Реальные PG timestamps: старая транзакция не публикует ответ раньше вопроса."""

import datetime as dt
from pathlib import Path

import psycopg
import pytest

from app.feed import service
from tests.helpers import dsn, new_run, sim_now


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["chat", "email", "sms", "push", "landing", "telegram_bot"])
async def test_notification_wall_clock_follows_question_from_another_transaction(seeded, monkeypatch, channel):
    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import notify_client
    from app.ingest.normalizer import create_signal, from_api_signal

    monkeypatch.setenv("TGBOT_ENABLED", "false")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as setup:
        run = await new_run(setup, "chronology notification")
        at = await sim_now(setup)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as older:
        started = (await (await older.execute("select now()")).fetchone())[0]
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as incoming:
            result = await create_signal(
                incoming,
                from_api_signal({"channel_code": "chat", "client_id": 1, "text": "Вопрос клиента о вкладе"}),
                source_code="api",
                run_id=run,
                sim_time=at,
            )
            assert result["status"] == "accepted"
            signal = result["signal_id"]
            await incoming.commit()
        ctx = ToolContext(older, run_id=run, agent_run_id=0, sim_time=at)
        result = await notify_client(ctx, 1, signal, None, channel, "ack_received", {"text": "Ответ банка"})
        question, answer = await (
            await older.execute(
                "select s.received_at,n.sent_at from notifications n join signals s on s.id=n.signal_id where n.id=%s",
                (result["notification_id"],),
            )
        ).fetchone()
        assert question > started
        assert answer >= question


@pytest.mark.asyncio
@pytest.mark.parametrize("author", ["agent", "human", "client_twin"])
async def test_reply_wall_time_follows_post_even_when_transaction_started_before_question(seeded, author):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as setup:
        run = await new_run(setup, "chronology feed")
        at = await sim_now(setup)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as old_transaction:
        started = (await (await old_transaction.execute("select now()")).fetchone())[0]
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as incoming:
            post = await service.create_post(
                incoming,
                run_id=run,
                platform="review_portal",
                author_nick="client_demo",
                text="Вопрос клиента о вкладе",
                posted_sim=at,
            )
            await incoming.commit()
        assert post["posted_at"] > started
        reply = await service.publish_reply(
            old_transaction,
            run_id=run,
            post_id=post["post_id"],
            author=author,
            text="Ответ банка на вопрос клиента",
            sim_time=at + dt.timedelta(minutes=1),
        )
        assert reply["published_at"] >= post["posted_at"]
        assert reply["latency_ms"] == (reply["published_at"] - post["posted_at"]) // dt.timedelta(milliseconds=1)
        if author == "agent":
            duplicate = await service.publish_reply(
                old_transaction,
                run_id=run,
                post_id=post["post_id"],
                author=author,
                text="Повторная попытка ответа",
                sim_time=at + dt.timedelta(minutes=2),
            )
            assert duplicate["duplicate"] and duplicate["reply_id"] == reply["reply_id"]
        await old_transaction.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["chat", "email", "sms", "push", "landing", "telegram_bot"])
async def test_emulated_channel_reply_uses_own_post_llm_effect_clock(seeded, monkeypatch, channel):
    from app.agent.graph import load_deps
    from app.agent.tools.write import notify_client
    from app.ingest.normalizer import create_signal, from_api_signal
    from tests.helpers import MOCK_PROFILE, mock_chain
    from tests.integration.test_behavior_runtime import setup

    monkeypatch.setenv("TGBOT_ENABLED", "false")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, before, sim = await setup(conn, monkeypatch, seeded)
        incoming = await create_signal(
            conn,
            from_api_signal(
                {"channel_code": "chat", "client_id": client, "text": "Вопрос клиента о работе приложения"}
            ),
            source_code="api",
            run_id=run,
            sim_time=before,
        )
        assert incoming["status"] == "accepted"
        signal = incoming["signal_id"]
        agent = (
            await (
                await conn.execute(
                    "insert into agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) values('agent',%s,%s,%s,%s,'chronology-native-case') returning id",
                    (run, signal, client, before),
                )
            ).fetchone()
        )[0]
        deps = await load_deps(
            conn, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run, agent_run_id=agent, sim_time=before
        )
        await conn.commit()
        try:
            await sim.step(15)
            after = sim.clock.sim_time
            assert after > before
            note = await notify_client(
                deps.ctx, client, signal, None, channel, "ack_received", {"text": "Ответ банка после вопроса клиента"}
            )
            row = await (
                await conn.execute(
                    "select s.received_sim,n.sent_sim,n.status,n.sent_at>=s.received_at from notifications n join signals s on s.id=n.signal_id and s.run_id=n.run_id where n.id=%s",
                    (note["notification_id"],),
                )
            ).fetchone()
            assert row[2] == "sent" and row[3] is True
            assert row[0] <= row[1] == after
            await conn.commit()
            query = (Path(__file__).resolve().parents[3] / "scripts/reviews/channel_chronology.sql").read_text()
            report = (await (await conn.execute(query)).fetchone())[0]
            assert report["known_invariants_passed"] is True
            sample = next(item for item in report["notifications"] if item["channel_code"] == channel)
            assert sample["anchored_records"] >= 1 and sample["before_question_sim"] == 0
            # Только тестовая незакоммиченная legacy-инверсия: сам audit обязан её заметить.
            await conn.execute(
                "update notifications set sent_sim=%s where id=%s",
                (row[0] - dt.timedelta(seconds=1), note["notification_id"]),
            )
            bad = (await (await conn.execute(query)).fetchone())[0]
            assert bad["known_invariants_passed"] is False
            assert (
                next(item for item in bad["notifications"] if item["channel_code"] == channel)["before_question_sim"]
                == 1
            )
            await conn.rollback()
        finally:
            await sim.conn.close()
