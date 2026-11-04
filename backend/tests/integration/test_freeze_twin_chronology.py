"""Freeze: реальная цепочка граф → ответ банка → двойник → дочерний граф."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent.graph import process_signal
from app.agent.prompts import load
from app.contracts.registry import deref
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.sim.twins import TwinService
from app.trace.privacy import mask
from tests.helpers import MOCK_PROFILE, advance_sim, dsn, mock_chain, new_run, run_agent_on, sim_now


class AskingTwin(MockProvider):
    """Управляем только ответом LLM; записи и побочные эффекты выполняет production."""

    calls = 0

    async def complete_structured(self, messages, schema, profile, *, timeout_s):
        self.calls += 1
        _, usage, _ = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
        obj = {
            "reaction": "asks_again",
            "tone": "irritated",
            "satisfaction": 0.2,
            "churn_intent": False,
            "text_ru": "В приложении по-прежнему не открывается вклад. Когда восстановите работу?",
        }
        return obj, usage, json.dumps(obj, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("advance_hours", [0, 1])
async def test_bank_twin_child_graph_preserves_chronology_and_lineage(seeded, monkeypatch, advance_hours):
    monkeypatch.setenv("TGBOT_ENABLED", "false")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "Freeze native twin chronology")
        now = await sim_now(conn)
        # Бюджет двойника набирается настоящими mock-проходами, без подмены token counters.
        for attempt in range(8):
            # Отдельный synthetic клиент: прогрев бюджета не превращается в repeat_3plus HITL.
            client = (
                await (
                    await conn.execute(
                        "insert into clients(display_name,segment_code,psychotype_code,region_code,city_id,clv_estimate_rub) "
                        "select 'Клиент проверки хронологии','mass','anxious',region_code,city_id,100000 "
                        "from clients order by id limit 1 returning id"
                    )
                ).fetchone()
            )[0]
            parent, state = await run_agent_on(
                conn,
                f"В приложении Банка не открывается вклад. Прошу помочь. Проверка {attempt + 1}.",
                client_id=client,
                run_id=run,
                sim_time=now,
            )
            await conn.commit()
            notice = await (
                await conn.execute(
                    "select id,body from notifications where run_id=%s and signal_id=%s "
                    "and client_id=%s and status in ('sent','delivered') order by id limit 1",
                    (run, parent, client),
                )
            ).fetchone()
            assert notice is not None, state
            total = (
                await (
                    await conn.execute(
                        "select coalesce(sum(total_tokens),0) from agent_runs where sim_run_id=%s and kind='agent'",
                        (run,),
                    )
                ).fetchone()
            )[0]
            segment, psychotype = await (
                await conn.execute("select segment_code,psychotype_code from clients where id=%s", (client,))
            ).fetchone()
            content = json.dumps(
                {"segment": segment, "psychotype": psychotype, "message": mask(notice[1], 1500)},
                ensure_ascii=False,
            )
            estimate = (
                len(load("twin").body) + len(content) + len(json.dumps(deref("agent/client_twin_reaction")))
            ) // 2 + 400
            if int(total * 0.15) >= estimate:
                break
        else:
            pytest.fail("Настоящие mock-проходы не набрали достаточный бюджет для двойника")
        if advance_hours:
            await advance_sim(conn, advance_hours)
        await conn.commit()

    twin = AskingTwin()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as conn:
        service = TwinService(ProviderChain([twin], append_mock=False), MOCK_PROFILE)
        twin_agent = await service.react(conn, notice[0])
        assert twin_agent is not None and twin.calls == 1
        child = await (
            await conn.execute(
                "select id,run_id,client_id,parent_signal_id from signals where run_id=%s and parent_signal_id=%s",
                (run, parent),
            )
        ).fetchone()
        assert child is not None and child["run_id"] == run and child["client_id"] == client
        assert child["parent_signal_id"] == parent
        # Повторная доставка не создаёт второй LLM-вызов/дочерний вход.
        assert await service.react(conn, notice[0]) is None and twin.calls == 1

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        state = await process_signal(conn, signal_id=child["id"], chain=mock_chain(), profile=MOCK_PROFILE)
        assert state is not None
        await conn.commit()
        timeline = await (
            await conn.execute(
                "select p.received_at,n.sent_at,r.created_at,c.received_at,cn.sent_at,"
                "p.received_sim,n.sent_sim,r.reacted_sim,c.received_sim,cn.sent_sim,"
                "p.run_id,n.run_id,r.run_id,c.run_id,cn.run_id "
                "from signals p join notifications n on n.id=%s and n.signal_id=p.id "
                "join client_reactions r on r.notification_id=n.id "
                "join signals c on c.parent_signal_id=p.id and c.id=%s "
                "join notifications cn on cn.signal_id=c.id and cn.run_id=c.run_id "
                "where p.id=%s and cn.status in ('sent','delivered') order by cn.id limit 1",
                (notice[0], child["id"], parent),
            )
        ).fetchone()
        assert timeline is not None, state
        assert list(timeline[:5]) == sorted(timeline[:5])
        assert all(value is not None for value in timeline[5:10])
        assert list(timeline[5:10]) == sorted(timeline[5:10])
        assert timeline[10:] == (run,) * 5
        if advance_hours:
            assert timeline[9] >= now + dt.timedelta(hours=advance_hours)
        query = (Path(__file__).resolve().parents[3] / "scripts/reviews/channel_chronology.sql").read_text()
        audit = (await (await conn.execute(query)).fetchone())[0]
        assert audit["known_invariants_passed"] is True
        for key in ("reaction_to_bank_notification", "twin_child_to_bank_notification"):
            assert audit[key]["records"] >= 1
            assert audit[key]["anchored_records"] >= 1
            assert audit[key]["before_bank_sim"] == audit[key]["before_bank_real"] == audit[key]["foreign_run"] == 0
