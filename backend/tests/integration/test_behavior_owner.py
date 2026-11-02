"""T-161: actual PG proposal, two connections/restart/receipts до RNG."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.contracts.events.behavior.psychotype_params import PsychotypeParams
from app.sim.behavior.model import complaint_timing
from app.sim.behavior.owner import BehaviorOwner
from app.sim.behavior.policy import DemoPolicy
from app.sim.behavior.store import BehaviorStore
from app.sim.rng import SimRng
from tests.helpers import dsn, new_run

ROOT = Path(__file__).resolve().parents[3]
POLICY = DemoPolicy.load(ROOT / "data/behavior/demo_policy.review.yaml", validation_only=True)


@pytest.fixture
def behavior_db(seeded: str) -> str:
    # Только own scratch suite: proposal не добавляется в Alembic/schema.sql.
    with psycopg.connect(dsn(seeded)) as conn:
        conn.execute((ROOT / "docs/reviews/T-161-storage-proposal.sql").read_text())
    return seeded


async def prepare(conn):
    now = (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone())[0]
    run = await new_run(conn, "T161 proposal", kind="free")
    await conn.execute("update sim_state set seed=1,rng_state=%s where id=1", (Jsonb(SimRng(1).dump_state()),))
    await conn.execute("update sim_runs set seed=1 where id=%s", (run,))
    client, params = await (
        await conn.execute(
            "select c.id,p.params from clients c join psychotypes p on p.code=c.psychotype_code where c.psychotype_code='anxious' and c.segment_code='mass' order by c.id limit 1"
        )
    ).fetchone()
    fault = (
        await (
            await conn.execute(
                "insert into faults(run_id,system_code,error_code,started_sim) values(%s,'sub_deposits','DEP-TIMEOUT-503',%s) returning id",
                (run, now),
            )
        ).fetchone()
    )[0]
    operations = []
    for index in range(2):
        operation = (
            await (
                await conn.execute(
                    "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) values(%s,%s,'deposit','deposit_open',ARRAY['sub_deposits'],'failed','DEP-TIMEOUT-503',%s,%s) returning id",
                    (run, client, fault, now + dt.timedelta(seconds=index)),
                )
            ).fetchone()
        )[0]
        operations.append(operation)
    await conn.commit()
    return run, client, now, params, operations


@pytest.mark.asyncio
async def test_restart_same_fault_operations_draw_once_and_normalizer_timer_is_durable(behavior_db: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            store = BehaviorStore(conn)
            assert await store.enqueue_operation(run_id=run, operation_id=operations[0])
            assert await store.enqueue_operation(run_id=run, operation_id=operations[1])
            saved = await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now + dt.timedelta(seconds=1))
            control = SimRng(1)
            params = PsychotypeParams.model_validate(raw)
            due, _ = complaint_timing(params, now, control)
            lo, hi = (item.root for item in params.patience_days)
            control.uniform(lo, hi)
            assert saved == control.dump_state()
            assert due is not None
            assert (
                await (await conn.execute("select count(*) from behavior_causes where run_id=%s", (run,))).fetchone()
            ) == (2,)
            assert (
                await (
                    await conn.execute(
                        "select count(*) from behavior_work where run_id=%s and kind='complaint'", (run,)
                    )
                ).fetchone()
            ) == (1,)
    # Реальное новое соединение и новый объект; никакой очереди старого процесса нет.
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        async with conn.transaction():
            first = await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=due)
            signal = await (
                await conn.execute(
                    "select id,client_id,source_operation_id,source_fault_id,received_sim,classification,meta from signals where run_id=%s",
                    (run,),
                )
            ).fetchone()
            assert signal is not None and signal[1] == client and signal[2] == operations[0] and signal[4] == due
            assert signal[5] is None and "gold" not in signal[6] and "generator_hint" not in signal[6]
            assert (
                await (
                    await conn.execute("select status from ingest_messages where signal_id=%s", (signal[0],))
                ).fetchone()
            ) == ("accepted",)
            assert await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=due) == first
            assert not await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
            assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()) == (
                1,
            )


@pytest.mark.asyncio
async def test_two_connections_same_logical_tick_do_not_double_draw(behavior_db: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
            due = (
                await (
                    await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
                ).fetchone()
            )[0]
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=due)
    target = BehaviorOwner.next_tick(due)

    async def tick():
        async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
            async with conn.transaction():
                return await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=target)

    one, two = await asyncio.gather(tick(), tick())
    assert one == two
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        assert (
            await (
                await conn.execute(
                    "select count(*) from behavior_tick_receipts where run_id=%s and client_id=%s and logical_tick_sim=%s",
                    (run, client, target),
                )
            ).fetchone()
        ) == (1,)


@pytest.mark.asyncio
async def test_rollback_restores_evidence_receipts_state_and_rng_before_retry(behavior_db: str, monkeypatch) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
        original = BehaviorOwner._event

        async def broken(*args, **kwargs):
            raise RuntimeError("injected transition event failure")

        monkeypatch.setattr(BehaviorOwner, "_event", broken)
        with pytest.raises(RuntimeError, match="injected transition"):
            async with conn.transaction():
                await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
        assert (
            await (await conn.execute("select count(*) from behavior_runtime where run_id=%s", (run,))).fetchone()
        ) == (0,)
        assert (
            await (await conn.execute("select count(*) from behavior_receipts where run_id=%s", (run,))).fetchone()
        ) == (0,)
        assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0] == SimRng(
            1
        ).dump_state()
        monkeypatch.setattr(BehaviorOwner, "_event", original)
        await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
        assert (
            await (await conn.execute("select count(*) from behavior_runtime where run_id=%s", (run,))).fetchone()
        ) == (1,)


@pytest.mark.asyncio
async def test_actual_twin_callback_records_observation_without_overwriting_care(behavior_db: str) -> None:
    from psycopg.rows import dict_row

    from app.llm.base import LLMProfile
    from app.llm.failover import ProviderChain
    from app.llm.mock import MockProvider
    from app.sim.behavior.store import record_twin_evidence
    from app.sim.twins import TwinService

    class FakeTwin(MockProvider):
        calls = 0

        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            self.calls += 1
            obj, usage, raw = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
            return (
                {
                    "reaction": "satisfied",
                    "tone": "positive",
                    "satisfaction": 0.99,
                    "churn_intent": False,
                    "text_ru": "",
                },
                usage,
                raw,
            )

    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
            due = (
                await (
                    await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
                ).fetchone()
            )[0]
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=due)
            signal = (await (await conn.execute("select id from signals where run_id=%s", (run,))).fetchone())[0]
            await conn.execute("update signals set origin='scenario' where id=%s", (signal,))
            await conn.execute(
                "insert into agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,outcome,total_tokens,prompt_version) values('agent',%s,%s,%s,%s,'completed',1000000,'synthetic-budget-fixture')",
                (run, signal, client, due),
            )
            notification = (
                await (
                    await conn.execute(
                        "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,template_code,body,status) values(%s,'client',%s,%s,'chat','ack_received','Мы получили ваше обращение','queued') returning id",
                        (run, client, signal),
                    )
                ).fetchone()
            )[0]
            assert not await BehaviorStore(conn).enqueue_notification(run_id=run, notification_id=notification)
            assert (
                await (
                    await conn.execute(
                        "select care_score from client_states where run_id=%s and client_id=%s and is_current",
                        (run, client),
                    )
                ).fetchone()
            )[0] == 0
            await conn.execute(
                "update notifications set status='sent',sent_sim=%s where id=%s",
                (due + dt.timedelta(minutes=1), notification),
            )
            assert await BehaviorStore(conn).enqueue_notification(run_id=run, notification_id=notification)
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=due + dt.timedelta(minutes=1))
            before = (
                await (
                    await conn.execute(
                        "select care_score from client_states where run_id=%s and client_id=%s and is_current",
                        (run, client),
                    )
                ).fetchone()
            )[0]
            assert 0 < before < 0.99
    provider = FakeTwin()
    chain = ProviderChain([provider], append_mock=False)
    profile = LLMProfile(code="mock", provider="mock", model="mock", role="main")
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db), autocommit=True, row_factory=dict_row) as conn:
        service = TwinService(chain, profile, behavior_sink=record_twin_evidence)
        agent = await service.react(conn, notification)
        assert agent is not None and provider.calls == 1
        row = await (
            await conn.execute("select satisfaction from client_reactions where agent_run_id=%s", (agent,))
        ).fetchone()
        assert row["satisfaction"] == __import__("decimal").Decimal(".990")
        row = await (
            await conn.execute(
                "select care_score from client_states where run_id=%s and client_id=%s and is_current", (run, client)
            )
        ).fetchone()
        assert row["care_score"] == before  # Сам TwinService care не меняет в новой границе.
        async with conn.transaction():
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=due + dt.timedelta(minutes=1))
        row = await (
            await conn.execute(
                "select care_score from client_states where run_id=%s and client_id=%s and is_current", (run, client)
            )
        ).fetchone()
        assert row["care_score"] == before
        row = await (
            await conn.execute(
                "select count(*) count from behavior_evidence where run_id=%s and source_kind='twin_reaction' and consumed_sim is not null",
                (run,),
            )
        ).fetchone()
        assert row["count"] == 1
        assert await service.react(conn, notification) is None and provider.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("breach", [False, True])
async def test_verified_sla_resolution_uses_components_and_never_closes_account(behavior_db: str, breach: bool) -> None:
    from app.sim.events import EventBus

    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            store = BehaviorStore(conn)
            owner = BehaviorOwner(conn, POLICY)
            await store.enqueue_operation(run_id=run, operation_id=operations[0])
            await owner.advance(run_id=run, to_sim=now)
            due = (
                await (
                    await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
                ).fetchone()
            )[0]
            await owner.advance(run_id=run, to_sim=due)
            signal, fault = await (
                await conn.execute("select id,source_fault_id from signals where run_id=%s", (run,))
            ).fetchone()
            incident = (
                await (
                    await conn.execute(
                        "insert into incidents(run_id,title,incident_type,product_code,system_code,error_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,fault_id,primary_client_id) values(%s,'T161 verified source','tech_fault','deposit','sub_deposits','DEP-TIMEOUT-503','team_deposits','medium','high',2,'in_progress','behavior_model',%s,%s,%s,%s,%s) returning id",
                        (run, due, due + dt.timedelta(days=1), due + dt.timedelta(hours=1), fault, client),
                    )
                ).fetchone()
            )[0]
            await conn.execute(
                "insert into incident_signals(incident_id,signal_id,linked_sim) values(%s,%s,%s)",
                (incident, signal, due),
            )
            if breach:
                await EventBus(conn).emit(
                    run,
                    "sla.report_missing",
                    {
                        "event_type": "sla.report_missing",
                        "incident_id": incident,
                        "team": "team_deposits",
                        "due_sim": (due + dt.timedelta(minutes=1)).isoformat(),
                        "sim_time": (due + dt.timedelta(minutes=1)).isoformat(),
                    },
                    due + dt.timedelta(minutes=1),
                )
                event = (
                    await (
                        await conn.execute(
                            "select id from sim_events where run_id=%s and event_type='sla.report_missing'", (run,)
                        )
                    ).fetchone()
                )[0]
                assert await store.enqueue_sla(run_id=run, client_id=client, event_id=event)
            body, variables = await (
                await conn.execute(
                    "select body,variables from notification_templates where code='resolved' and lang='ru' and segment_code is null order by id limit 1"
                )
            ).fetchone()
            for variable in variables:
                body = body.replace(
                    "{{ " + variable + " }}", "Клиент" if variable == "name" else "Проблема устранена"
                ).replace("{{" + variable + "}}", "Проблема устранена")
            notification = (
                await (
                    await conn.execute(
                        "insert into notifications(run_id,recipient_type,client_id,signal_id,incident_id,channel_code,template_code,body,status,sent_sim) values(%s,'client',%s,%s,%s,'chat','resolved',%s,'sent',%s) returning id",
                        (run, client, signal, incident, body, due + dt.timedelta(minutes=2)),
                    )
                ).fetchone()
            )[0]
            assert await store.enqueue_notification(run_id=run, notification_id=notification)
            await owner.advance(run_id=run, to_sim=due + dt.timedelta(minutes=2))
            await conn.execute("update faults set resolved_sim=%s where id=%s", (due + dt.timedelta(minutes=3), fault))
            await conn.execute(
                "update incidents set status='resolved',resolved_sim=%s where id=%s",
                (due + dt.timedelta(minutes=3), incident),
            )
            assert await store.enqueue_resolution(run_id=run, client_id=client, incident_id=incident)
            await owner.advance(run_id=run, to_sim=due + dt.timedelta(minutes=3))
            current = await owner.episode(run, client)
            assert current["state"] == ("satisfied" if breach else "retained")
            assert current["incident_id"] == incident and current["signal_id"] == signal
            assert current["sla_breached"] is breach and current["closed_sim"] is not None
            assert (
                await (
                    await conn.execute(
                        "select count(*) from behavior_work where run_id=%s and status='pending'", (run,)
                    )
                ).fetchone()
            ) == (0,)
            assert (
                await (await conn.execute("select count(*) from churn_events where run_id=%s", (run,))).fetchone()
            ) == (0,)
            assert (
                await (await conn.execute("select count(*) from ledger_entries where run_id=%s", (run,))).fetchone()
            ) == (0,)
            latest = (
                await (
                    await conn.execute(
                        "select payload from sim_events where run_id=%s and event_type in ('client.retained','client.state_changed') order by id desc limit 1",
                        (run,),
                    )
                ).fetchone()
            )[0]
            assert latest["incident_id"] == incident and latest["to_state"] == current["state"]


@pytest.mark.asyncio
async def test_proposal_snapshot_guard_and_current_state_unique(behavior_db: str) -> None:
    import copy

    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
            await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now)
            snapshot = (
                await (
                    await conn.execute(
                        "select care_snapshot from behavior_runtime where run_id=%s and client_id=%s", (run, client)
                    )
                ).fetchone()
            )[0]
            for change in (
                {"version": True},
                {"version": 2},
                {"tone_violated": 1},
                {"first_reply_at": "2026-11-02T00:00:00"},
            ):
                with pytest.raises(psycopg.errors.CheckViolation):
                    async with conn.transaction():
                        await conn.execute(
                            "update behavior_runtime set care_snapshot=%s where run_id=%s and client_id=%s",
                            (Jsonb(copy.deepcopy(snapshot) | change), run, client),
                        )
            with pytest.raises(psycopg.errors.UniqueViolation):
                async with conn.transaction():
                    await conn.execute(
                        "insert into client_states(run_id,client_id,state,since_sim,trigger,care_score) values(%s,%s,'waiting',%s,'timer',0)",
                        (run, client, now),
                    )
            with pytest.raises(ValueError):
                await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=True)


@pytest.mark.asyncio
async def test_proposal_refuses_legacy_duplicate_currents_without_deleting_them(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        # Actual0017 уже установлена fixture; воспроизводим старую0016 boundary
        # только внутри откатываемой scratch TX, сохраняя прежние assertions.
        await conn.execute("drop index behavior_client_states_current_key")
        await conn.execute(
            "drop table behavior_runs,behavior_pending_signals,behavior_agent_intents,behavior_runtime,behavior_evidence,behavior_causes,behavior_work,behavior_receipts,behavior_tick_receipts cascade"
        )
        for _ in range(2):
            await conn.execute(
                "insert into client_states(run_id,client_id,state,since_sim,trigger) values(%s,%s,'waiting',%s,'timer')",
                (run, client, now),
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="explicit operator reconciliation"):
            async with conn.transaction():
                await conn.execute((ROOT / "docs/reviews/T-161-storage-proposal.sql").read_text())
        assert (
            await (
                await conn.execute(
                    "select count(*) from client_states where run_id=%s and client_id=%s and is_current", (run, client)
                )
            ).fetchone()
        ) == (2,)
        assert (await (await conn.execute("select to_regclass('public.behavior_runtime')")).fetchone()) == (None,)
        await conn.rollback()


@pytest.mark.asyncio
async def test_fault_adapter_admits_all_known_clients_without_sample_cap(behavior_db: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            fault = (
                await (await conn.execute("select fault_id from operations where id=%s", (operations[0],))).fetchone()
            )[0]
            clients = await (
                await conn.execute("select id from clients where id<>%s order by id limit 60", (client,))
            ).fetchall()
            for (other,) in clients:
                await conn.execute(
                    "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) values(%s,%s,'deposit','deposit_open',ARRAY['sub_deposits'],'failed','DEP-TIMEOUT-503',%s,%s)",
                    (run, other, fault, now),
                )
            store = BehaviorStore(conn)
            assert await store.enqueue_fault(run_id=run, fault_id=fault) == 62
            assert await store.enqueue_fault(run_id=run, fault_id=fault) == 0
            first = await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now + dt.timedelta(seconds=1))
            assert (
                await (await conn.execute("select count(*) from behavior_runtime where run_id=%s", (run,))).fetchone()
            ) == (61,)
            assert (
                await (await conn.execute("select count(*) from behavior_causes where run_id=%s", (run,))).fetchone()
            ) == (62,)
            assert await BehaviorOwner(conn, POLICY).advance(run_id=run, to_sim=now + dt.timedelta(seconds=1)) == first


@pytest.mark.asyncio
async def test_invalid_causal_source_is_rejected_before_evidence_or_rng(behavior_db: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            fault = (
                await (await conn.execute("select fault_id from operations where id=%s", (operations[0],))).fetchone()
            )[0]
            region = (
                await (
                    await conn.execute(
                        "select code from regions where code<>(select region_code from clients where id=%s) order by code limit 1",
                        (client,),
                    )
                ).fetchone()
            )[0]
            mutations = [
                ("update operations set started_sim=%s where id=%s", (now - dt.timedelta(seconds=1), operations[0])),
                ("update operations set system_path=ARRAY['mobile_app'] where id=%s", (operations[0],)),
                ("update operations set error_code='APP-LOGIN-FAIL' where id=%s", (operations[0],)),
                ("update faults set region_codes=%s where id=%s", ([region], fault)),
                ("update faults set resolved_sim=%s where id=%s", (now, fault)),
            ]
            for sql, args in mutations:
                with pytest.raises(ValueError, match="подтверждённой"):
                    async with conn.transaction():
                        await conn.execute(sql, args)
                        await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])
                assert (
                    await (
                        await conn.execute("select count(*) from behavior_evidence where run_id=%s", (run,))
                    ).fetchone()
                ) == (0,)
                assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[
                    0
                ] == SimRng(1).dump_state()
            assert await BehaviorStore(conn).enqueue_operation(run_id=run, operation_id=operations[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_owner", [False, True])
async def test_terminal_client_or_lost_owner_never_reopens_episode(behavior_db: str, broken_owner: bool) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, _, operations = await prepare(conn)
        async with conn.transaction():
            store, owner = BehaviorStore(conn), BehaviorOwner(conn, POLICY)
            await store.enqueue_operation(run_id=run, operation_id=operations[0])
            await owner.advance(run_id=run, to_sim=now)
            before = (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0]
            if broken_owner:
                await conn.execute("update client_states set is_current=false where run_id=%s", (run,))
            else:
                await conn.execute("update client_states set state='churned' where run_id=%s and is_current", (run,))
                await conn.execute("update behavior_runtime set closed_sim=%s where run_id=%s", (now, run))
            await store.enqueue_operation(run_id=run, operation_id=operations[1])
            if broken_owner:
                with pytest.raises(ValueError, match="reconciliation"):
                    async with conn.transaction():
                        await owner.advance(run_id=run, to_sim=now + dt.timedelta(seconds=1))
            else:
                assert await owner.advance(run_id=run, to_sim=now + dt.timedelta(seconds=1)) == before
                assert (await owner.episode(run, client))["state"] == "churned"
            assert (await (await conn.execute("select rng_state from sim_state where id=1")).fetchone())[0] == before
            assert (
                await (await conn.execute("select episode_no from behavior_runtime where run_id=%s", (run,))).fetchone()
            ) == (1,)


@pytest.mark.asyncio
async def test_gift_credit_requires_actual_done_task_and_matching_sent_offer(behavior_db: str) -> None:
    from app.sim.behavior.care import GiftEvidence
    from app.sim.behavior.facts import notification_observations

    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, raw, operations = await prepare(conn)
        async with conn.transaction():
            store, owner = BehaviorStore(conn), BehaviorOwner(conn, POLICY)
            await store.enqueue_operation(run_id=run, operation_id=operations[0])
            await owner.advance(run_id=run, to_sim=now)
            current = await owner.episode(run, client)
            fault = (
                await (await conn.execute("select fault_id from operations where id=%s", (operations[0],))).fetchone()
            )[0]
            signal = (
                await (
                    await conn.execute(
                        "insert into signals(run_id,client_id,channel_code,text,received_sim,source_operation_id,source_fault_id) values(%s,%s,'chat','Запрос компенсации',%s,%s,%s) returning id",
                        (run, client, now, operations[0], fault),
                    )
                ).fetchone()
            )[0]
            incident = (
                await (
                    await conn.execute(
                        "insert into incidents(run_id,title,incident_type,product_code,system_code,error_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,fault_id,primary_client_id) values(%s,'T161 gift evidence','tech_fault','deposit','sub_deposits','DEP-TIMEOUT-503','team_deposits','medium','high',2,'in_progress','behavior_model',%s,%s,%s,%s,%s) returning id",
                        (run, now, now + dt.timedelta(days=1), now + dt.timedelta(hours=1), fault, client),
                    )
                ).fetchone()
            )[0]
            body, variables = await (
                await conn.execute(
                    "select body,variables from notification_templates where code='gift_offer' and lang='ru' and segment_code is null order by id limit 1"
                )
            ).fetchone()
            for variable in variables:
                value = "Клиент" if variable == "name" else "Тестовый подарок"
                body = body.replace("{{ " + variable + " }}", value).replace("{{" + variable + "}}", value)
            notice = (
                await (
                    await conn.execute(
                        "insert into notifications(run_id,recipient_type,client_id,signal_id,incident_id,channel_code,template_code,body,status,sent_sim) values(%s,'client',%s,%s,%s,'chat','gift_offer',%s,'sent',%s) returning id",
                        (run, client, signal, incident, body, now),
                    )
                ).fetchone()
            )[0]
            # Это только fixtures уже выданных источников; ни issuer, ни ledger не вызываются.
            payloads = [
                (
                    {
                        "gift": {"gift_code": "bonus_points", "points": 10},
                        "issued": {"label": "Тестовый подарок", "sim_time": now.isoformat()},
                    },
                    "done",
                ),
                (
                    {
                        "gift": {"privilege_code": "lounge_pass"},
                        "issued": {"label": "Тестовый подарок", "sim_time": now.isoformat()},
                    },
                    "done",
                ),
                (
                    {
                        "gift": {"gift_code": "bonus_points", "points": 999},
                        "issued": {"label": "Тестовый подарок", "sim_time": now.isoformat()},
                    },
                    "open",
                ),
                (
                    {
                        "gift": {"gift_code": "bonus_points", "points": 999},
                        "issued": {"label": "Другое предложение", "sim_time": now.isoformat()},
                    },
                    "done",
                ),
                (
                    {
                        "gift": {"gift_code": "bonus_points", "points": 999},
                        "issued": {
                            "label": "Тестовый подарок",
                            "sim_time": (now + dt.timedelta(seconds=1)).isoformat(),
                        },
                    },
                    "done",
                ),
                (
                    {
                        "gift": {"gift_code": "personal_call"},
                        "issued": {"label": "Тестовый подарок", "sim_time": now.isoformat()},
                    },
                    "done",
                ),
            ]
            for payload, status in payloads:
                await conn.execute(
                    "insert into tasks(run_id,kind,incident_id,client_id,status,created_sim,payload) values(%s,'gift',%s,%s,%s,%s,%s)",
                    (run, incident, client, status, now, Jsonb(payload)),
                )
            observations = await notification_observations(conn, current, notice)
            gifts = [item for item in observations if isinstance(item, GiftEvidence)]
            assert len(gifts) == 2
            assert {item.kind for item in gifts} == {"bonus_points", "partner_privilege"}
            assert {item.elasticity for item in gifts} == {raw["gift_elasticity"], raw["privilege_elasticity"]}
            before = await (
                await conn.execute("select payload from tasks where run_id=%s order by id", (run,))
            ).fetchall()
            assert await store.enqueue_notification(run_id=run, notification_id=notice)
            await owner.advance(run_id=run, to_sim=now)
            after = await owner.episode(run, client)
            assert after["care_snapshot"]["components"]["gift_fit"] == max(
                raw["gift_elasticity"], raw["privilege_elasticity"]
            )
            assert (
                await (await conn.execute("select payload from tasks where run_id=%s order by id", (run,))).fetchall()
            ) == before
            assert (
                await (await conn.execute("select count(*) from ledger_entries where run_id=%s", (run,))).fetchone()
            ) == (0,)


@pytest.mark.asyncio
async def test_agent_legacy_state_reader_and_writer_keep_baseline_and_foreign_runs(behavior_db: str) -> None:
    from app.agent.tools.base import ToolContext
    from app.agent.tools.read import get_client_profile
    from app.agent.tools.write import set_client_state

    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, _, _ = await prepare(conn)
        baseline = (
            await (await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")).fetchone()
        )[0]
        foreign = await new_run(conn, "foreign state", kind="scenario")
        for owner, state in ((baseline, "affected"), (run, "waiting"), (foreign, "churned")):
            await conn.execute(
                "insert into client_states(run_id,client_id,state,since_sim,trigger) values(%s,%s,%s,%s,'timer')",
                (owner, client, state, now),
            )
        ctx = ToolContext(conn, run_id=run, agent_run_id=0, sim_time=now)
        assert (await get_client_profile(ctx, client))["state"] == "waiting"
        changed = await set_client_state(ctx, client, "complaining", "agent:complaint")
        assert changed["status"] == "applied" and changed["state"] == "complaining"
        assert (await get_client_profile(ctx, client))["state"] == "complaining"
        assert (
            await (
                await conn.execute(
                    "select run_id,state from client_states where client_id=%s and is_current order by run_id",
                    (client,),
                )
            ).fetchall()
        ) == sorted([(baseline, "affected"), (run, "complaining"), (foreign, "churned")])
        await conn.execute("update client_states set is_current=false where run_id=%s and client_id=%s", (run, client))
        assert (await get_client_profile(ctx, client))["state"] == "affected"
        await conn.rollback()


@pytest.mark.asyncio
async def test_agent_sink_is_pending_atomic_and_never_treats_request_as_closure(behavior_db: str) -> None:
    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import set_client_state
    from app.sim.behavior.store import record_agent_state_intent

    async with await psycopg.AsyncConnection.connect(dsn(behavior_db)) as conn:
        run, client, now, _, operations = await prepare(conn)
        async with conn.transaction():
            store, owner = BehaviorStore(conn), BehaviorOwner(conn, POLICY)
            await store.enqueue_operation(run_id=run, operation_id=operations[0])
            await owner.advance(run_id=run, to_sim=now)
            due = (
                await (
                    await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
                ).fetchone()
            )[0]
            await owner.advance(run_id=run, to_sim=due)
            signal = (await (await conn.execute("select id from signals where run_id=%s", (run,))).fetchone())[0]
            agent = (
                await (
                    await conn.execute(
                        "insert into agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) values('agent',%s,%s,%s,%s,'synthetic-intent-fixture') returning id",
                        (run, signal, client, due),
                    )
                ).fetchone()
            )[0]
            from app.agent.graph import load_deps
            from tests.helpers import MOCK_PROFILE, mock_chain

            deps = await load_deps(
                conn,
                chain=mock_chain(),
                profile=MOCK_PROFILE,
                run_id=run,
                agent_run_id=agent,
                sim_time=due,
                state_evidence_sink=record_agent_state_intent,
            )
            ctx = deps.ctx
            assert ctx.conn is conn and ctx.state_evidence_sink is record_agent_state_intent
            with pytest.raises(RuntimeError, match="rollback graph effect"):
                async with conn.transaction():
                    pending = await set_client_state(ctx, client, "churned", "agent:complaint", signal)
                    assert pending["status"] == "pending" and pending["state"] == "waiting"
                    raise RuntimeError("rollback graph effect")
            assert (
                await (
                    await conn.execute("select count(*) from behavior_agent_intents where run_id=%s", (run,))
                ).fetchone()
            ) == (0,)
            for request in ("churned", "satisfied", "retained", "churn_intent"):
                first = await set_client_state(ctx, client, request, "agent:complaint", signal)
                second = await set_client_state(ctx, client, request, "agent:complaint", signal)
                assert first == second and first["state"] == "waiting" and first["requested_state"] == request
            await owner.advance(run_id=run, to_sim=due)
            assert (await owner.episode(run, client))["state"] == "waiting"
            assert (await owner.episode(run, client))["closed_sim"] is None
            # Только actual persisted classification flag подтверждает churn intent.
            await conn.execute(
                "update signals set classification=jsonb_build_object('flags',jsonb_build_array('churn_intent')) where id=%s",
                (signal,),
            )
            await set_client_state(ctx, client, "churn_intent", "agent:verified_flag", signal)
            await owner.advance(run_id=run, to_sim=due)
            assert (await owner.episode(run, client))["state"] == "churn_intent"
            from app.sim.runs import create_run

            foreign = await create_run(conn, kind="scenario", label="foreign intent", seed=42, sim_time=due)
            foreign_ctx = ToolContext(
                conn, run_id=foreign, agent_run_id=agent, sim_time=due, state_evidence_sink=record_agent_state_intent
            )
            with pytest.raises(ValueError, match="не принадлежит"):
                await set_client_state(foreign_ctx, client, "satisfied", "agent:complaint", signal)
            assert (
                await (
                    await conn.execute("select count(*) from behavior_agent_intents where run_id=%s", (foreign,))
                ).fetchone()
            ) == (0,)
