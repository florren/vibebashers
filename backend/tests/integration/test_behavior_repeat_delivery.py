"""T-161: repeat source, reply deadline gate и transport-grant isolation."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.sim.behavior.owner import BehaviorOwner
from app.sim.rng import SimRng
from tests.helpers import dsn

from .test_behavior_owner import POLICY
from .test_behavior_runtime import setup
from .test_behavior_signal_evidence import source


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_signal_only_repeat_known_or_unknown_product_and_restart_without_grant(seeded, monkeypatch, unknown):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        # Seed8 выбирает repeat и telegram_bot при неизменных catalog weights.
        await conn.execute("update sim_state set seed=8,rng_state=%s where id=1", (Jsonb(SimRng(8).dump_state()),))
        await conn.execute("update sim_runs set seed=8 where id=%s", (run,))
        parent, _ = await source(conn, run, client, now, unknown_product=unknown, known_product=not unknown)
        await conn.execute(
            "update signals set meta=meta||%s where id=%s",
            (Jsonb({"telegram_chat_id": 112233, "delivery_grant": "untrusted-parent-metadata"}), parent),
        )
        before = await (
            await conn.execute(
                "select (select count(*) from channel_runtime.telegram_signal_bindings),(select count(*) from channel_runtime.telegram_client_bindings)"
            )
        ).fetchone()
        await conn.commit()
        async with conn.transaction():
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
    # Новый owner/connection до исходного deadline, никаких old memory timers.
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        async with conn.transaction():
            owner = BehaviorOwner(conn, POLICY)
            current = await owner.episode(run, client)
            deadline = now + dt.timedelta(minutes=current["first_response_min"])
            final_rng = await owner.advance(run_id=run, to_sim=deadline)
            children = await (
                await conn.execute(
                    "select id,text,source_operation_id,source_fault_id,meta,channel_code,origin,client_id from signals where parent_signal_id=%s and run_id=%s",
                    (parent, run),
                )
            ).fetchall()
            assert len(children) == 1
            child = children[0]
            assert child[2:4] == (None, None) and child[5:] == ("telegram_bot", "sim", client)
            assert child[4]["text_source"] == ("parent_signal" if unknown else "t019")
            if unknown:
                assert (
                    child[1]
                    == (await (await conn.execute("select text from signals where id=%s", (parent,))).fetchone())[0]
                )
            assert "telegram_chat_id" not in child[4] and "delivery_grant" not in child[4] and "gold" not in child[4]
            assert (await owner.episode(run, client))["repeat_count"] == 1
            assert (
                await (
                    await conn.execute(
                        "select (select count(*) from channel_runtime.telegram_signal_bindings),(select count(*) from channel_runtime.telegram_client_bindings)"
                    )
                ).fetchone()
            ) == before
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        async with conn.transaction():
            assert await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=deadline) == final_rng
            assert (
                await (
                    await conn.execute(
                        "select count(*) from signals where parent_signal_id=%s and run_id=%s", (parent, run)
                    )
                ).fetchone()
            ) == (1,)


@pytest.mark.asyncio
async def test_reply_gate_matches_first_reply_scope_status_and_exact_deadline(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        parent, _ = await source(conn, run, client, now)
        unrelated, _ = await source(conn, run, client, now, sentiment="positive", kind="gratitude")
        await conn.commit()
        async with conn.transaction():
            owner = BehaviorOwner(conn, POLICY)
            await owner.advance(run_id=run, to_sim=now)
            current = await owner.episode(run, client)
            deadline = now + dt.timedelta(minutes=current["first_response_min"])
            foreign = (
                await (
                    await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")
                ).fetchone()
            )[0]
            other = (
                await (
                    await conn.execute("select id from clients where id<>%s order by id limit 1", (client,))
                ).fetchone()
            )[0]
            cases = [
                ("sent", run, client, parent, "ack_received", deadline, "Мы получили ваше обращение", True),
                ("delivered", run, client, parent, "ack_received", deadline, "Мы получили ваше обращение", True),
                ("queued", run, client, parent, "ack_received", None, "Мы получили ваше обращение", False),
                ("unknown", run, client, parent, "ack_received", None, "Мы получили ваше обращение", False),
                ("failed", run, client, parent, "ack_received", None, "Мы получили ваше обращение", False),
                (
                    "sent",
                    run,
                    client,
                    parent,
                    "ack_received",
                    deadline + dt.timedelta(microseconds=1),
                    "Мы получили ваше обращение",
                    False,
                ),
                ("sent", run, client, parent, "gift_offer", deadline, "Подарок начислен", False),
                ("sent", run, client, parent, "dm_invite", deadline, "Напишите нам лично", False),
                ("sent", run, client, parent, "team_notice", deadline, "Сотрудники проверяют обращение", False),
                ("sent", run, client, parent, "ack_received", deadline, "Гарантируем отсутствие ошибок", False),
                ("sent", foreign, client, parent, "ack_received", deadline, "Мы получили ваше обращение", False),
                ("sent", run, other, parent, "ack_received", deadline, "Мы получили ваше обращение", False),
                ("sent", run, client, unrelated, "ack_received", deadline, "Мы получили ваше обращение", False),
            ]
            for index, (status, rid, cid, signal, template, sent, body, expected) in enumerate(cases):
                notice = (
                    await (
                        await conn.execute(
                            "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,template_code,body,status,sent_sim) values(%s,'client',%s,%s,'chat',%s,%s,%s,%s) returning id",
                            (rid, cid, signal, template, body, status, sent),
                        )
                    ).fetchone()
                )[0]
                assert await owner._answered(current, parent, deadline) is expected, index
                await conn.execute("delete from notifications where id=%s", (notice,))


@pytest.mark.asyncio
async def test_actual_twin_and_canonical_child_share_one_repeat_receipt_without_care_overwrite(seeded, monkeypatch):
    import json

    from psycopg.rows import dict_row

    from app.agent.tools.base import ToolContext
    from app.economics.calibration import PIPELINE
    from app.llm.base import LLMProfile
    from app.llm.failover import ProviderChain
    from app.llm.mock import MockProvider
    from app.sim.behavior.runtime import capture, twin_sink
    from app.sim.behavior.signals import record_classified
    from app.sim.behavior.store import record_agent_state_intent
    from app.sim.twins import TwinService

    class RepeatingTwin(MockProvider):
        calls = 0

        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            self.calls += 1
            _, usage, _ = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
            obj = {
                "reaction": "asks_again",
                "tone": "irritated",
                "satisfaction": 0.99,
                "churn_intent": False,
                "text_ru": "Повторяю жалобу: ответа по существу нет, помогите с обращением.",
            }
            return obj, usage, json.dumps(obj, ensure_ascii=False)

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        parent, ctx = await source(conn, run, client, now, unknown_product=True)
        await conn.execute("update signals set origin='jury' where id=%s", (parent,))
        # Только controlled budget fixture: не live usage/качество LLM.
        await conn.execute(
            "update agent_runs set total_tokens=1000000,outcome='completed',finished_at=now() where id=%s",
            (ctx.agent_run_id,),
        )
        notice = (
            await (
                await conn.execute(
                    "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,template_code,body,status,sent_sim) values(%s,'client',%s,%s,'chat','ack_received','Мы получили ваше обращение','sent',%s) returning id",
                    (run, client, parent, now),
                )
            ).fetchone()
        )[0]
        await conn.commit()
        async with conn.transaction():
            await capture(conn, run)
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
            care = (await BehaviorOwner(conn, POLICY).episode(run, client))["care_score"]
            assert 0 < float(care) < 0.99
    provider = RepeatingTwin()
    chain = ProviderChain([provider], append_mock=False)
    profile = LLMProfile(code="mock", provider="mock", model="mock", role="main")
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as conn:
        service = TwinService(chain, profile, behavior_sink=twin_sink)
        agent = await service.react(conn, notice)
        assert agent is not None and provider.calls == 1
        async with conn.transaction():
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
        current = await BehaviorOwner(conn, POLICY).episode(run, client)
        assert current["repeat_count"] == 1 and current["care_score"] == care
        child = (
            await (
                await conn.execute("select id from signals where run_id=%s and parent_signal_id=%s", (run, parent))
            ).fetchone()
        )["id"]
        classification = (
            await (await conn.execute("select classification from signals where id=%s", (parent,))).fetchone()
        )["classification"]
        classification["flags"] = sorted({*classification["flags"], "repeat"})
        async with conn.transaction():
            await conn.execute("update signals set classification=%s where id=%s", (Jsonb(classification), child))
            child_agent = (
                await (
                    await conn.execute(
                        "insert into agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) values('agent',%s,%s,%s,%s,'synthetic-child-fixture') returning id",
                        (run, child, client, now),
                    )
                ).fetchone()
            )["id"]
            await conn.execute(
                "insert into agent_steps(run_id,seq,node,status,input,output) values(%s,1,'classify','ok','{}',%s)",
                (child_agent, Jsonb(classification | {"score_pipeline": PIPELINE})),
            )
            child_ctx = ToolContext(
                conn, run_id=run, agent_run_id=child_agent, sim_time=now, state_evidence_sink=record_agent_state_intent
            )
            await record_classified(child_ctx, child)
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
            current = await BehaviorOwner(conn, POLICY).episode(run, client)
            assert current["repeat_count"] == 1 and current["care_score"] == care
            # Pausedclock: parentack и child имеют один SimTime, но старый ответ
            # не обслуживает новый child. Новый direct childack в тот же tick — да.
            assert not await BehaviorOwner(conn, POLICY)._answered(
                current, child, now + dt.timedelta(minutes=current["first_response_min"])
            )
            await conn.execute(
                "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,template_code,body,status,sent_sim) values(%s,'client',%s,%s,'chat','ack_received','Мы получили повторное обращение','sent',%s)",
                (run, client, child, now),
            )
            assert await BehaviorOwner(conn, POLICY)._answered(
                current, child, now + dt.timedelta(minutes=current["first_response_min"])
            )
            count = (
                await (
                    await conn.execute(
                        "select count(*) n from behavior_receipts where run_id=%s and source_kind='signal' and source_id=%s and action='repeat'",
                        (run, child),
                    )
                ).fetchone()
            )["n"]
            assert count == 1
        assert await service.react(conn, notice) is None and provider.calls == 1
