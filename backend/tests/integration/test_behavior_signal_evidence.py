"""Already-complained mapping: canonical факты, не свободный state/gold."""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent.tools.base import ToolContext
from app.agent.tools.write import set_client_state
from app.contracts.registry import deref, validate
from app.economics.calibration import PIPELINE
from app.llm.mock import MockProvider
from app.sim.behavior.owner import BehaviorOwner
from app.sim.behavior.signals import record_classified
from app.sim.behavior.store import record_agent_state_intent
from app.sim.rng import SimRng
from tests.helpers import MOCK_PROFILE, dsn, run_agent_on

from .test_behavior_owner import POLICY
from .test_behavior_runtime import setup


async def source(
    conn,
    run,
    client,
    now,
    *,
    sentiment="negative",
    flags=(),
    kind="service_quality",
    canonical=True,
    unknown_product=False,
    known_product=False,
):
    # Полный schema-valid controlled fixture; это не LLM accuracy claim.
    obj, _, _ = await MockProvider().complete_structured(
        [{"role": "user", "content": "Сотрудник грубо ответил, обслуживанием недоволен"}],
        deref("agent/classification"),
        MOCK_PROFILE,
        timeout_s=1,
    )
    obj.update(sentiment=sentiment, flags=list(flags), signal_type=kind)
    if unknown_product:
        obj["product"] = None
    if known_product:
        obj["product"] = "debit_card"
    assert not validate(obj, "agent/classification")
    signal = (
        await (
            await conn.execute(
                "insert into signals(run_id,client_id,channel_code,text,received_sim,classification,meta) values(%s,%s,'chat','Синтетический проверочный запрос',%s,%s,%s) returning id",
                (run, client, now, Jsonb(obj), Jsonb({"gold": {"sentiment": "negative", "flags": ["churn_intent"]}})),
            )
        ).fetchone()
    )[0]
    agent = (
        await (
            await conn.execute(
                "insert into agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) values('agent',%s,%s,%s,%s,'synthetic-classifier-fixture') returning id",
                (run, signal, client, now),
            )
        ).fetchone()
    )[0]
    if canonical:
        await conn.execute(
            "insert into agent_steps(run_id,seq,node,status,input,output,finished_at) values(%s,1,'classify','ok','{}',%s,now())",
            (agent, Jsonb(obj | {"score_pipeline": PIPELINE})),
        )
    ctx = ToolContext(conn, run_id=run, agent_run_id=agent, sim_time=now, state_evidence_sink=record_agent_state_intent)
    await record_classified(ctx, signal)
    return signal, ctx


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sentiment,flags,kind,canonical,opens",
    [
        ("negative", (), "service_quality", True, True),
        ("neutral", (), "info_request", True, False),
        ("positive", (), "gratitude", True, False),
        ("neutral", ("churn_intent",), "info_request", True, True),
        ("neutral", ("repeat",), "service_quality", True, True),
        ("negative", (), "service_quality", False, False),
    ],
)
async def test_signal_mapping_one_patience_no_backdated_probability_and_new_connection(
    seeded, monkeypatch, sentiment, flags, kind, canonical, opens
):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        signal, ctx = await source(
            conn, run, client, now, sentiment=sentiment, flags=flags, kind=kind, canonical=canonical
        )
        # Arbitrary requested churned не меняет admissibility настоящего source.
        pending = await set_client_state(ctx, client, "churned", "agent:request", signal)
        assert pending["status"] == "pending" and pending["state"] == "calm"
        await conn.commit()
        async with conn.transaction():
            owner = BehaviorOwner(conn, POLICY)
            state = await owner.advance(run_id=run, to_sim=now)
            current = await owner.episode(run, client)
            control = SimRng(1)
            if opens:
                assert current["first_complaint_sim"] == now
                assert current["state"] == ("churn_intent" if "churn_intent" in flags else "waiting")
                assert current["repeat_count"] == (1 if "repeat" in flags else 0)
                raw = (
                    await (
                        await conn.execute(
                            "select params from psychotypes where code=%s", (current["psychotype_code"],)
                        )
                    ).fetchone()
                )[0]
                control.uniform(*raw["patience_days"])
                patience = current["patience_due_sim"]
                assert (
                    await (
                        await conn.execute(
                            "select count(*) from behavior_work where run_id=%s and kind='complaint'", (run,)
                        )
                    ).fetchone()
                ) == (0,)
                assert (
                    await (
                        await conn.execute("select count(*) from behavior_causes where run_id=%s", (run,))
                    ).fetchone()
                ) == (0,)
                assert (
                    await (
                        await conn.execute(
                            "select source_id from behavior_receipts where run_id=%s and source_kind='signal' and action='cause:1'",
                            (run,),
                        )
                    ).fetchone()
                ) == (signal,)
            else:
                assert current is None
                patience = None
            assert state == control.dump_state()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        async with conn.transaction():
            assert await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now) == state
            if opens:
                assert (await BehaviorOwner(conn, POLICY).episode(run, client))["patience_due_sim"] == patience


@pytest.mark.asyncio
async def test_signal_receipt_rng_rollback_and_foreign_scope(seeded, monkeypatch):
    from app.sim.events import EventBus

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        signal, ctx = await source(conn, run, client, now)
        await conn.commit()
        original = EventBus.emit

        async def broken(*args, **kwargs):
            raise RuntimeError("injected classified transition")

        monkeypatch.setattr(EventBus, "emit", broken)
        with pytest.raises(RuntimeError, match="injected classified transition"):
            async with conn.transaction():
                await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
        assert (
            await (await conn.execute("select count(*) from behavior_receipts where run_id=%s", (run,))).fetchone()
        ) == (0,)
        assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0] == SimRng(
            1
        ).dump_state()
        await conn.rollback()
        monkeypatch.setattr(EventBus, "emit", original)
        async with conn.transaction():
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
        baseline = (
            await (await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")).fetchone()
        )[0]
        before = (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0]
        foreign_ctx = ToolContext(
            conn,
            run_id=baseline,
            agent_run_id=ctx.agent_run_id,
            sim_time=now,
            state_evidence_sink=record_agent_state_intent,
        )
        with pytest.raises(ValueError, match="не принадлежит"):
            async with conn.transaction():
                await set_client_state(foreign_ctx, client, "complaining", "agent:foreign", signal)
        assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0] == before
        assert (
            await (await conn.execute("select count(*) from behavior_runtime where run_id=%s", (baseline,))).fetchone()
        ) == (0,)


@pytest.mark.asyncio
async def test_actual_mock_graph_classifier_hook_opens_signal_only_episode(seeded, monkeypatch):
    from app.sim.behavior.runtime import capture

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        signal, state = await run_agent_on(
            conn,
            "Ужасный сервис, хамство и грубость сотрудника! Не могу добиться ответа.",
            client_id=client,
            run_id=run,
            sim_time=now,
        )
        assert state["classification"]["sentiment"] == "negative"
        assert (await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()) == (
            0,
        )
        async with conn.transaction():
            await capture(conn, run)
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
            current = await BehaviorOwner(conn, POLICY).episode(run, client)
            assert current is not None and current["signal_id"] == signal
            assert (
                await (await conn.execute("select count(*) from behavior_causes where run_id=%s", (run,))).fetchone()
            ) == (0,)


@pytest.mark.asyncio
async def test_signal_only_care_and_resolution_need_all_real_signal_causes(seeded, monkeypatch):
    import datetime as dt

    from app.sim.behavior.runtime import capture

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        first, _ = await source(conn, run, client, now)
        second, _ = await source(conn, run, client, now)
        incidents = []
        for signal in (first, second):
            incident = (
                await (
                    await conn.execute(
                        "insert into incidents(run_id,title,incident_type,product_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,primary_client_id) values(%s,'T161 signal cause','service_quality','debit_card','team_cx','medium','high',2,'in_progress','agent',%s,%s,%s,%s) returning id",
                        (run, now, now + dt.timedelta(days=1), now + dt.timedelta(hours=1), client),
                    )
                ).fetchone()
            )[0]
            incidents.append(incident)
            await conn.execute(
                "insert into incident_signals(incident_id,signal_id,linked_sim) values(%s,%s,%s)",
                (incident, signal, now),
            )
        body, variables = await (
            await conn.execute(
                "select body,variables from notification_templates where code='resolved' and lang='ru' and segment_code is null order by id limit 1"
            )
        ).fetchone()
        for variable in variables:
            value = "Клиент" if variable == "name" else "Проблема устранена"
            body = body.replace("{{ " + variable + " }}", value).replace("{{" + variable + "}}", value)
        await conn.execute(
            "insert into notifications(run_id,recipient_type,client_id,signal_id,incident_id,channel_code,template_code,body,status,sent_sim) values(%s,'client',%s,%s,%s,'chat','resolved',%s,'sent',%s)",
            (run, client, first, incidents[0], body, now + dt.timedelta(minutes=1)),
        )
        await conn.execute(
            "update incidents set status='resolved',resolved_sim=%s where id=%s",
            (now + dt.timedelta(minutes=2), incidents[0]),
        )
        await conn.commit()
        async with conn.transaction():
            await capture(conn, run)
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now + dt.timedelta(minutes=2))
            current = await BehaviorOwner(conn, POLICY).episode(run, client)
            patience = current["patience_due_sim"]
            assert float(current["care_score"]) >= POLICY.spec["retained_threshold"]
            assert current["closed_sim"] is None and current["state"] == "waiting"
            assert (
                await (
                    await conn.execute("select count(*) from behavior_work where run_id=%s and kind='patience'", (run,))
                ).fetchone()
            ) == (1,)
        await conn.execute(
            "update incidents set status='resolved',resolved_sim=%s where id=%s",
            (now + dt.timedelta(minutes=3), incidents[1]),
        )
        await conn.commit()
        async with conn.transaction():
            await capture(conn, run)
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now + dt.timedelta(minutes=3))
            current = await BehaviorOwner(conn, POLICY).episode(run, client)
            assert current["state"] == "retained" and current["closed_sim"] is not None
            assert current["patience_due_sim"] == patience
            assert (
                await (await conn.execute("select count(*) from operations where run_id=%s", (run,))).fetchone()
            ) == (0,)
            assert (
                await (await conn.execute("select count(*) from ledger_entries where run_id=%s", (run,))).fetchone()
            ) == (0,)


@pytest.mark.asyncio
async def test_resolved_signal_episode_reopens_on_new_connection_without_old_care(seeded, monkeypatch):
    from app.contracts.enums import ClientState

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        first, _ = await source(conn, run, client, now, unknown_product=True)
        await conn.commit()
        async with conn.transaction():
            owner = BehaviorOwner(conn, POLICY)
            await owner.advance(run_id=run, to_sim=now)
            current = await owner.episode(run, client)
            old_due = current["patience_due_sim"]
            # Закрытие уже доказано отдельным actual resolution test; здесь
            # исходный fixture — закрытый episode с сохранённой immutable history.
            await owner._transition(current, ClientState.RETAINED, now, "closure", score=0.6)
            await conn.execute("update behavior_runtime set closed_sim=%s where run_id=%s", (now, run))
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        later = now + __import__("datetime").timedelta(minutes=5)
        second, _ = await source(conn, run, client, later, unknown_product=True)
        await conn.commit()
        async with conn.transaction():
            owner = BehaviorOwner(conn, POLICY)
            await owner.advance(run_id=run, to_sim=later)
            current = await owner.episode(run, client)
            assert current["episode_no"] == 2 and current["closed_sim"] is None
            assert current["first_complaint_sim"] == later and current["signal_id"] == second and second != first
            assert current["patience_due_sim"] != old_due and float(current["care_score"]) == 0
            assert (
                await (
                    await conn.execute(
                        "select count(*) from behavior_receipts where run_id=%s and source_kind='signal' and action='cause:2'",
                        (run,),
                    )
                ).fetchone()
            ) == (1,)
