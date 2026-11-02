"""T-161: задержка Mock LLM не переносит happened time жалобы на время записи."""

from __future__ import annotations

import asyncio
import datetime as dt

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent.graph import load_deps
from app.agent.tools.write import notify_client
from app.contracts.registry import deref, validate
from app.economics.calibration import PIPELINE
from app.llm.mock import MockProvider
from app.sim.behavior.owner import BehaviorOwner
from app.sim.behavior.signals import record_classified
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

from .test_behavior_inactive import case
from .test_behavior_owner import POLICY


@pytest.mark.asyncio
async def test_delayed_classification_keeps_complaint_t0_notice_t3_observation_t5(seeded, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Delayed(MockProvider):
        async def complete_structured(self, *args, **kwargs):
            entered.set()
            await release.wait()
            result, usage, meta = await super().complete_structured(*args, **kwargs)
            # Controlled negative response проверяет chronology, не accuracy Mock.
            result["sentiment"] = "negative"
            return result, usage, meta

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, t0, signal, agent = await case(conn, monkeypatch, seeded)
        text = "Сотрудник грубо накричал на меня, обслуживанием недоволен"
        await conn.execute("update signals set text=%s where id=%s", (text, signal))
        deadline = (
            await (
                await conn.execute(
                    "select s.first_response_min from clients c join segments s on s.code=c.segment_code where c.id=%s",
                    (client,),
                )
            ).fetchone()
        )[0]
        await conn.commit()
        # Контекст создаётся до await модели, как в production graph.
        deps = await load_deps(
            conn, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run, agent_run_id=agent, sim_time=t0
        )
        await conn.commit()
        sim = await load_sim(seeded)
        pending = asyncio.create_task(
            Delayed().complete_structured(
                [{"role": "user", "content": text}],
                deref("agent/classification"),
                MOCK_PROFILE,
                timeout_s=1,
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            await sim.step(float(deadline) * 3)
            t3 = t0 + dt.timedelta(minutes=float(deadline) * 3)
            notice = await notify_client(
                deps.ctx,
                client,
                signal,
                None,
                "chat",
                "ack_received",
                {"name": "Клиент", "summary": "проверяем обращение", "sla_minutes": deadline},
            )
            sent = (
                await (
                    await conn.execute("select sent_sim from notifications where id=%s", (notice["notification_id"],))
                ).fetchone()
            )[0]
            assert sent == t3  # До исправления producer записывал frozen T0.
            await conn.commit()
            await sim.step(float(deadline) * 2)
            t5 = t0 + dt.timedelta(minutes=float(deadline) * 5)
            assert sim.clock.sim_time == t5
            release.set()
            classification, _, _ = await asyncio.wait_for(pending, timeout=2)
            assert not validate(classification, "agent/classification")
            assert classification["sentiment"] == "negative"
            await conn.execute("update signals set classification=%s where id=%s", (Jsonb(classification), signal))
            await conn.execute(
                "insert into agent_steps(run_id,seq,node,status,input,output,finished_at) values(%s,1,'classify','ok','{}',%s,now())",
                (agent, Jsonb(classification | {"score_pipeline": PIPELINE})),
            )
            await record_classified(deps.ctx, signal)
            observed = (
                await (
                    await conn.execute("select observed_sim from behavior_agent_intents where run_id=%s", (run,))
                ).fetchone()
            )[0]
            assert observed == t5
            await conn.commit()
            await sim.step(0.01)
            owner = BehaviorOwner(conn, POLICY)
            episode = await owner.episode(run, client)
            assert episode["first_complaint_sim"] == t0
            assert episode["next_hazard_sim"] > t5
            assert episode["care_snapshot"]["components"]["proactive"] == 0
            assert episode["care_snapshot"]["components"]["speed"] == 0
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
            await sim.conn.close()


async def load_sim(url):
    # Только загрузка актуального Simulator, без нового run/RNG reset.
    from app.sim.engine import Simulator

    sim = Simulator(dsn=url)
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0)
    return sim


@pytest.mark.asyncio
@pytest.mark.parametrize("historical", [False, True])
async def test_refund_effect_time_is_current_own_clock_or_frozen_historical_context(seeded, monkeypatch, historical):
    from app.abs import service as abs_svc
    from app.agent.tools.abs import refund_fee
    from app.rules.engine import check_rules
    from tests.helpers import new_run

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        await abs_svc.backfill_ledger(conn)
        await conn.commit()
        operation, client = await (
            await conn.execute(
                "select id,client_id from operations where error_code='PROC-QR-FEE-CHARGED' and method='qr_sbp' and op_type='card_payment' and fee_amount>0 order by id limit 1"
            )
        ).fetchone()
        run, client, t0, signal, agent = await case(conn, monkeypatch, seeded, client_override=client)
        await conn.execute(
            "update signals set text='Списали комиссию за оплату по QR, прошу вернуть.' where id=%s", (signal,)
        )
        operation_data = (
            await (await conn.execute("select to_jsonb(o) from operations o where id=%s", (operation,))).fetchone()
        )[0]
        operation_data["operation_id"] = operation
        matched = await check_rules(
            conn, run_id=run, signal_id=signal, agent_run_id=agent, operations=[operation_data], tariff_fee_pct=0
        )
        assert any(row["rule_code"] == "RULE-QR-FEE-001" for row in matched)
        deps = await load_deps(
            conn, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run, agent_run_id=agent, sim_time=t0
        )
        await conn.commit()
        if historical:
            other = await new_run(conn, "native foreign clock", kind="free")
            assert other != run
        sim = await load_sim(seeded)
        try:
            await sim.step(15)
            now = sim.clock.sim_time
            assert now > t0
            effect = await refund_fee(deps.ctx, operation, None, "RULE-QR-FEE-001", "проверенный возврат")
            assert not effect["duplicate"]
            await conn.commit()
            posted = (
                await (
                    await conn.execute("select posted_sim from ledger_entries where id=%s", (effect["entry_id"],))
                ).fetchone()
            )[0]
            assert posted == (t0 if historical else now)
            assert deps.ctx.run_id == run and deps.ctx.agent_run_id == agent
            await sim.step(15)
            again = await refund_fee(deps.ctx, operation, None, "RULE-QR-FEE-001", "повтор запроса")
            assert again["duplicate"] and again["entry_id"] == effect["entry_id"]
            await conn.commit()
            assert (
                await (
                    await conn.execute("select posted_sim from ledger_entries where id=%s", (effect["entry_id"],))
                ).fetchone()
            ) == (posted,)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from ledger_entries where run_id=%s and operation_id=%s and kind='refund'",
                        (run, operation),
                    )
                ).fetchone()
            ) == (1,)
            assert await abs_svc.check_invariant(conn) == []
        finally:
            await sim.conn.close()
