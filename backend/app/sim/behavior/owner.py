"""Единственный transactional behavior writer внутри существующей Sim tick TX.

Внешний tick сохраняет состояние своего RNG; owner блокирует sim_state и
возвращает следующий snapshot. Здесь нет connect/commit/runtimeDDL или RAM-очереди.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from app.contracts.enums import ClientState
from app.contracts.events.behavior.psychotype_params import PsychotypeParams
from app.ingest.normalizer import create_signal
from app.sim.behavior.care import (
    CareComponents,
    CareContext,
    CareObservation,
    CareState,
    CommunicationEvidence,
    SlaEvidence,
    eligible_reply,
    evaluate_care,
)
from app.sim.behavior.codec import dump_care, load_care
from app.sim.behavior.facts import notification_observations, related, signal_resolved
from app.sim.behavior.model import Snapshot, complaint_timing, draw_repeat, hazard_score
from app.sim.behavior.policy import DemoPolicy
from app.sim.behavior.store import BehaviorStore, positive_ids
from app.sim.clock import add_working_hours
from app.sim.events import EventBus
from app.sim.rng import SimRng
from app.sim.textgen import TextGen


class BehaviorOwner:
    def __init__(self, conn: psycopg.AsyncConnection[Any], policy: DemoPolicy) -> None:
        self.conn, self.policy = conn, policy
        self.store = BehaviorStore(conn)
        self.bus = EventBus(conn)

    async def one(self, sql: str, args: tuple[Any, ...]) -> Any:
        async with self.conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, args)
            return await cur.fetchone()

    async def episode(self, run: int, client: int) -> Any:
        current = await self.one(
            "select b.*,cs.state,cs.care_score,cs.incident_id,cs.signal_id,cs.since_sim,cs.is_current from behavior_runtime b "
            "join client_states cs on cs.id=b.state_id and cs.run_id=b.run_id and cs.client_id=b.client_id "
            "where b.run_id=%s and b.client_id=%s for update of b",
            (run, client),
        )
        if current is not None and not current["is_current"]:
            raise ValueError("behavior state потерял владение is_current; требуется reconciliation")
        return current

    async def advance(self, *, run_id: int, to_sim: dt.datetime, allow_paused: bool = False) -> dict[str, Any]:
        self.store.require_transaction()
        self.generated_signals = 0
        self.cancellation_observed_at = to_sim
        if not isinstance(allow_paused, bool):
            raise ValueError("allow_paused должен быть явным bool")
        positive_ids(run_id)
        if not isinstance(to_sim, dt.datetime) or to_sim.utcoffset() is None:
            raise ValueError("нужен aware sim_time")
        state = await self.one("select seed,rng_state,current_run_id from sim_state where id=1 for update", ())
        run = await self.one("select kind,status from sim_runs where id=%s", (run_id,))
        if (
            state is None
            or state["current_run_id"] != run_id
            or run is None
            or run["kind"] not in ("free", "scenario")
            or (run["status"] != "running" and not (allow_paused and run["status"] == "paused"))
        ):
            raise ValueError("behavior advance требует текущий running free/scenario run")
        async with self.conn.cursor(row_factory=tuple_row) as cursor:
            await cursor.execute("select code,params from psychotypes order by code")
            parameters = await cursor.fetchall()
            await cursor.execute("select code from segments order by code")
            segments = await cursor.fetchall()
        self.policy.preflight(dict(parameters), {row[0] for row in segments})
        rng = SimRng(state["seed"])
        rng.load_state(state["rng_state"])
        while (job := await self._next(run_id, to_sim)) is not None:
            at = job["at"]
            if job["kind"] == "evidence":
                await self._evidence(job["id"], at, rng)
            elif job["kind"] == "work":
                await self._work(job["id"], at, rng)
            else:
                await self._hazard(run_id, job["id"], at, rng)
        result = rng.dump_state()
        await self.conn.execute("update sim_state set rng_state=%s where id=1", (Jsonb(result),))
        return result

    async def _next(self, run: int, to: dt.datetime) -> Any:
        return await self.one(
            "select * from ("
            "select 'evidence'::text kind,id,observed_sim at,0 priority,client_id from behavior_evidence "
            "where run_id=%s and consumed_sim is null and observed_sim<=%s and "
            "(source_kind in ('operation','agent_state') or exists(select 1 from behavior_runtime b where b.run_id=behavior_evidence.run_id and b.client_id=behavior_evidence.client_id)) union all "
            "select 'work',w.id,w.due_sim,case w.kind when 'complaint' then 1 else 2 end,w.client_id "
            "from behavior_work w join behavior_runtime b using(run_id,client_id) "
            "where w.run_id=%s and w.status='pending' and w.episode_no=b.episode_no and b.closed_sim is null and w.due_sim<=%s union all "
            "select 'hazard',b.client_id,b.next_hazard_sim,3,b.client_id from behavior_runtime b join client_states c on c.id=b.state_id "
            "where b.run_id=%s and b.closed_sim is null and c.state in ('waiting','churn_intent') and b.next_hazard_sim<=%s"
            ") jobs order by at,priority,client_id,kind,id limit 1",
            (run, to, run, to, run, to),
        )

    @staticmethod
    def next_tick(at: dt.datetime) -> dt.datetime:
        if not isinstance(at, dt.datetime) or at.utcoffset() is None:
            raise ValueError("logical tick требует aware timestamp")
        seconds = (math.floor(at.timestamp() / 900) + 1) * 900
        return dt.datetime.fromtimestamp(seconds, dt.UTC)

    async def _evidence(self, source_id: int, at: dt.datetime, rng: SimRng) -> None:
        evidence = await self.one("select * from behavior_evidence where id=%s for update", (source_id,))
        assert evidence is not None
        if await self.store.receipt(
            run_id=evidence["run_id"],
            client_id=evidence["client_id"],
            source_kind="evidence",
            source_id=source_id,
            action="consume",
            at=at,
        ):
            if evidence["source_kind"] == "operation":
                await self._operation(evidence, at, rng)
            elif evidence["source_kind"] == "notification":
                await self._notification(evidence)
            elif evidence["source_kind"] == "twin_reaction":
                await self._twin(evidence, at)
            elif evidence["source_kind"] == "sla":
                await self._sla(evidence, at)
            elif evidence["source_kind"] == "resolution":
                await self._resolution(evidence, at)
            elif evidence["source_kind"] == "agent_state":
                await self._agent_intent(evidence, at, rng)
            else:
                raise ValueError("неподдерживаемый behavior evidence kind")
        await self.conn.execute("update behavior_evidence set consumed_sim=%s where id=%s", (at, source_id))

    async def _operation(self, evidence: Any, at: dt.datetime, rng: SimRng) -> None:
        run, client = evidence["run_id"], evidence["client_id"]
        operation = await self.one(
            "select *,behavior_valid_failed_operation(id,%s) valid_cause from operations where id=%s and run_id=%s and client_id=%s",
            (run, evidence["source_id"], run, client),
        )
        if operation is None or operation["status"] != "failed" or not operation["valid_cause"]:
            raise ValueError("исходный failed operation изменён или отсутствует")
        kind = "fault" if operation["fault_id"] is not None else "operation"
        source = operation["fault_id"] or operation["id"]
        fresh = await self.store.receipt(
            run_id=run, client_id=client, source_kind=kind, source_id=source, action="affect", at=at
        )
        current = await self.episode(run, client)
        if current is not None and current["state"] == ClientState.CHURNED.value:
            return
        if current is None or current["closed_sim"] is not None:
            if not fresh:
                return
            current, due, silent = await self._open(run, client, at, rng, current)
            await self.conn.execute(
                "update behavior_runtime set silent_decline=%s where run_id=%s and client_id=%s", (silent, run, client)
            )
            if due is None:
                await self._transition(current, ClientState.WAITING, at, "timer")
            else:
                await self._schedule(current, "complaint", operation["id"], due)
        await self.conn.execute(
            "insert into behavior_causes(run_id,client_id,episode_no,operation_id,fault_id) values(%s,%s,%s,%s,%s) "
            "on conflict do nothing",
            (run, client, current["episode_no"], operation["id"], operation["fault_id"]),
        )

    async def _open(
        self, run: int, client: int, at: dt.datetime, rng: SimRng, old: Any, *, source_signal: int | None = None
    ) -> Any:
        info = await self.one(
            "select c.psychotype_code,c.segment_code,p.params,s.first_response_min from clients c "
            "join psychotypes p on p.code=c.psychotype_code join segments s on s.code=c.segment_code where c.id=%s",
            (client,),
        )
        if info is None:
            raise ValueError("клиент не имеет явных behavior parameters")
        if old is None and await self.one(
            "select id from client_states where run_id=%s and client_id=%s and is_current", (run, client)
        ):
            raise ValueError("legacy state без component snapshot требует явного перехода/нового run")
        params = PsychotypeParams.model_validate(info["params"])
        lo, hi = (item.root for item in params.patience_days)
        due, silent = complaint_timing(params, at, rng) if source_signal is None else (None, False)
        patience = add_working_hours(at, rng.uniform(lo, hi) * 9)
        episode = (old["episode_no"] + 1) if old else 1
        care = CareState(CareComponents())
        if old:
            await self.conn.execute("update client_states set is_current=false where id=%s", (old["state_id"],))
        initial = ClientState.AFFECTED if source_signal is None else ClientState.COMPLAINING
        trigger = "fault" if source_signal is None else "signal_sent"
        created = await self.one(
            "insert into client_states(run_id,client_id,state,since_sim,trigger,care_score,signal_id) values(%s,%s,%s,%s,%s,0,%s) returning id",
            (run, client, initial.value, at, trigger, source_signal),
        )
        await self.conn.execute(
            "insert into behavior_runtime(run_id,client_id,episode_no,state_id,opened_sim,policy_hash,policy_source_sha256,"
            "policy_snapshot,params_snapshot,care_snapshot,patience_due_sim,next_hazard_sim,psychotype_code,segment_code,first_response_min) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict(run_id,client_id) do update set episode_no=excluded.episode_no,state_id=excluded.state_id,opened_sim=excluded.opened_sim,"
            "closed_sim=null,policy_hash=excluded.policy_hash,policy_source_sha256=excluded.policy_source_sha256,policy_snapshot=excluded.policy_snapshot,"
            "params_snapshot=excluded.params_snapshot,care_snapshot=excluded.care_snapshot,patience_due_sim=excluded.patience_due_sim,"
            "next_hazard_sim=excluded.next_hazard_sim,first_complaint_sim=null,repeat_count=0,sla_breached=false,silent_decline=false,"
            "psychotype_code=excluded.psychotype_code,segment_code=excluded.segment_code,first_response_min=excluded.first_response_min",
            (
                run,
                client,
                episode,
                created["id"],
                at,
                self.policy.sha256,
                self.policy.source_sha256,
                Jsonb(self.policy.spec),
                Jsonb(params.model_dump(mode="json")),
                Jsonb(dump_care(care)),
                patience,
                self.next_tick(at),
                info["psychotype_code"],
                info["segment_code"],
                info["first_response_min"],
            ),
        )
        current = await self.episode(run, client)
        await self._event(
            current,
            ClientState(old["state"]) if old else ClientState.CALM,
            initial,
            at,
            trigger,
            0.0,
            links={"signal_id": source_signal} if source_signal is not None else None,
        )
        await self._schedule(current, "patience", episode, patience)
        return current, due, silent

    async def _schedule(self, current: Any, kind: str, source: int, due: dt.datetime) -> None:
        await self.conn.execute(
            "insert into behavior_work(run_id,client_id,episode_no,kind,source_id,due_sim) values(%s,%s,%s,%s,%s,%s) "
            "on conflict do nothing",
            (current["run_id"], current["client_id"], current["episode_no"], kind, source, due),
        )

    async def _transition(
        self,
        current: Any,
        state: ClientState,
        at: dt.datetime,
        trigger: str,
        *,
        score: float | None = None,
        hazard: float | None = None,
        links: dict[str, int] | None = None,
    ) -> Any:
        before = ClientState(current["state"])
        score = float(current["care_score"] or 0) if score is None else score
        await self.conn.execute(
            "update client_states set is_current=false where id=%s and run_id=%s and client_id=%s",
            (current["state_id"], current["run_id"], current["client_id"]),
        )
        row = await self.one(
            "insert into client_states(run_id,client_id,state,since_sim,trigger,care_score,hazard,signal_id,incident_id) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
            (
                current["run_id"],
                current["client_id"],
                state.value,
                at,
                trigger,
                score,
                hazard,
                (links or {}).get("signal_id", current.get("signal_id")),
                (links or {}).get("incident_id", current.get("incident_id")),
            ),
        )
        await self.conn.execute(
            "update behavior_runtime set state_id=%s where run_id=%s and client_id=%s",
            (row["id"], current["run_id"], current["client_id"]),
        )
        await self._event(current, before, state, at, trigger, score, hazard, links=links)
        return await self.episode(current["run_id"], current["client_id"])

    async def _event(
        self,
        current: Any,
        before: ClientState,
        after: ClientState,
        at: dt.datetime,
        trigger: str,
        score: float,
        hazard: float | None = None,
        *,
        links: dict[str, int] | None = None,
    ) -> None:
        event = (
            "client.affected"
            if after == ClientState.AFFECTED and before != after
            else "client.churn_intent"
            if after == ClientState.CHURN_INTENT and before != after
            else "client.retained"
            if after == ClientState.RETAINED and before != after
            else "client.state_changed"
        )
        payload = {
            "event_type": event,
            "client_id": current["client_id"],
            "segment": current["segment_code"],
            "psychotype": current["psychotype_code"],
            "from_state": before.value,
            "to_state": after.value,
            "trigger": trigger,
            "care_score": score,
            "sim_time": at.isoformat(),
            "generated_by": "param",
        }
        if hazard is not None:
            payload["hazard"] = hazard
        payload.update(
            {
                key: value
                for key, value in (links or {}).items()
                if key in ("signal_id", "incident_id", "notification_id")
            }
        )
        correlation = uuid.uuid5(
            uuid.NAMESPACE_URL, f"cx-pulse/behavior/{current['run_id']}/{current['client_id']}/{current['episode_no']}"
        )
        await self.bus.emit(current["run_id"], event, payload, at, correlation_id=correlation)

    async def _work(self, source_id: int, at: dt.datetime, rng: SimRng) -> None:
        job = await self.one("select * from behavior_work where id=%s for update", (source_id,))
        current = await self.episode(job["run_id"], job["client_id"])
        if await self.store.receipt(
            run_id=job["run_id"],
            client_id=job["client_id"],
            source_kind="work",
            source_id=source_id,
            action=job["kind"],
            at=at,
        ):
            if job["kind"] == "complaint":
                await self._complaint(current, job["source_id"], at, rng)
            if job["kind"] == "repeat":
                answered = await self._answered(current, job["source_id"], at)
                if not answered and current["state"] == ClientState.WAITING.value:
                    selected = draw_repeat(PsychotypeParams.model_validate(current["params_snapshot"]), rng)
                    if selected is not None:
                        current = await self._transition(current, selected, at, "timer")
                        child = await self._repeat_signal(current, job["source_id"], at, rng)
                        await self._count_repeat(current, child, at)
            # patience — только durable eligibility для T164, без закрытия счёта.
        await self.conn.execute(
            "update behavior_work set status='consumed',consumed_sim=%s where id=%s", (at, source_id)
        )

    async def _count_repeat(self, current: Any, signal_id: int, at: dt.datetime) -> bool:
        fresh = await self.store.receipt(
            run_id=current["run_id"],
            client_id=current["client_id"],
            source_kind="signal",
            source_id=signal_id,
            action="repeat",
            at=at,
        )
        if fresh:
            await self.conn.execute(
                "update behavior_runtime set repeat_count=repeat_count+1 where run_id=%s and client_id=%s",
                (current["run_id"], current["client_id"]),
            )
        return fresh

    async def _answered(self, current: Any, signal_id: int, deadline: dt.datetime) -> bool:
        source = await self.one(
            "select received_sim,created_at from signals where id=%s and run_id=%s and client_id=%s",
            (signal_id, current["run_id"], current["client_id"]),
        )
        if source is None:
            raise ValueError("repeat timer не имеет исходный same-run/client signal")
        policy = self.pinned_policy(current)
        context = CareContext(current["opened_sim"], current["first_complaint_sim"], current["first_response_min"])
        async with self.conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(
                "select id,template_code from notifications where run_id=%s and client_id=%s and recipient_type in ('client','public') "
                "and status in ('sent','delivered') and sent_sim>=%s and sent_sim<=%s "
                "and (sent_sim>%s or signal_id=%s or (signal_id is null and created_at>=%s)) order by sent_sim,id",
                (
                    current["run_id"],
                    current["client_id"],
                    source["received_sim"],
                    deadline,
                    source["received_sim"],
                    signal_id,
                    source["created_at"],
                ),
            )
            notices = await cur.fetchall()
        for notice, template in notices:
            if template in policy.care.first_reply_excluded_templates:
                continue
            for observation in await notification_observations(self.conn, current, notice):
                if isinstance(observation, CommunicationEvidence) and eligible_reply(
                    observation, context=context, policy=policy.care
                ):
                    return True
        return False

    async def _repeat_signal(self, current: Any, parent_id: int, at: dt.datetime, rng: SimRng) -> int:
        from app.contracts.registry import validate

        parent = await self.one(
            "select s.*,ci.name_ru city,c.region_code from signals s join clients c on c.id=s.client_id "
            "join cities ci on ci.id=c.city_id where s.id=%s and s.run_id=%s and s.client_id=%s",
            (parent_id, current["run_id"], current["client_id"]),
        )
        if parent is None:
            raise ValueError("repeat source не принадлежит episode run/client")
        operation = None
        if parent["source_operation_id"] is not None:
            operation = await self.one(
                "select * from operations where id=%s and run_id=%s and client_id=%s",
                (parent["source_operation_id"], current["run_id"], current["client_id"]),
            )
            if operation is None:
                raise ValueError("repeat source_operation не принадлежит run/client")
        params = PsychotypeParams.model_validate(current["params_snapshot"])
        allowed = current["policy_snapshot"]["complaint"]["eligible_inbound_channels"]
        weights = {key: float(value.root) for key, value in params.channel_weights.items() if key in allowed}
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("repeat не имеет eligible inbound weights")
        channel = rng.weighted({key: value / total for key, value in weights.items()})
        classification = parent["classification"]
        known = isinstance(classification, dict) and not validate(classification, "agent/classification")
        product = classification.get("product") if known else operation["product_code"] if operation else None
        kind = classification["signal_type"] if known else "tech_fault" if operation else None
        template = None
        if product is not None:
            if not isinstance(kind, str):
                raise ValueError("known repeat product требует canonical signal type")
            generated = TextGen(rng).generate(
                kind, product, psychotype=current["psychotype_code"], city=parent["city"], channel=channel
            )
            text, language, template = generated.text, generated.gold["language"], generated.gold.get("template_id")
            text_source = "t019"
        else:
            text, language, text_source = parent["text"], parent["lang"], "parent_signal"
        await self.conn.execute(
            "insert into ingest_sources(code,kind,channel_code,enabled,is_external) values('behavior_param','rest','chat',false,false) on conflict(code) do nothing"
        )
        result = await create_signal(
            self.conn,
            {
                "external_id": f"behavior-repeat:{current['run_id']}:{current['client_id']}:{current['episode_no']}:{parent_id}",
                "channel": channel,
                "client": {"client_id": current["client_id"]},
                "text": text,
                "timestamp": at.isoformat(),
                "origin": "sim",
                "geo": {"source": "client_profile", "region_code": parent["region_code"]},
                "meta": {
                    "parent_signal_id": parent_id,
                    "behavior_policy_hash": current["policy_hash"],
                    "behavior_episode": current["episode_no"],
                    "source_operation_id": operation["id"] if operation else None,
                    "source_fault_id": operation["fault_id"] if operation else None,
                    "text_source": text_source,
                    "template_id": template,
                },
            },
            source_code="behavior_param",
            run_id=current["run_id"],
            sim_time=at,
        )
        if result["status"] != "accepted":
            raise ValueError("repeat не принят normalizer; требуется rollback")
        child = result["signal_id"]
        self.generated_signals += 1
        await self.conn.execute("update signals set lang=%s where id=%s", (language, child))
        await self._transition(current, ClientState.WAITING, at, "signal_sent", links={"signal_id": child})
        await self._schedule(current, "repeat", child, at + dt.timedelta(minutes=current["first_response_min"]))
        return int(child)

    async def _hazard(self, run: int, client: int, at: dt.datetime, rng: SimRng) -> None:
        current = await self.episode(run, client)
        inserted = await self.one(
            "insert into behavior_tick_receipts(run_id,client_id,logical_tick_sim) values(%s,%s,%s) on conflict do nothing returning client_id",
            (run, client, at),
        )
        if inserted:
            params = PsychotypeParams.model_validate(current["params_snapshot"])
            spec = json.dumps(current["policy_snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if hashlib.sha256(spec.encode()).hexdigest() != current["policy_hash"]:
                raise ValueError("pinned policy checksum нарушен")
            snapshot = Snapshot(
                ClientState(current["state"]),
                float(current["care_score"] or 0),
                current["repeat_count"],
                current["sla_breached"],
            )
            value = hazard_score(
                params,
                current["policy_snapshot"]["segment_multiplier"][current["segment_code"]],
                snapshot,
                repeat=bool(current["repeat_count"]),
            )
            if not 0 <= value <= 1:
                raise ValueError("raw hazard вне Bernoulli domain; tick отменён")
            await self.conn.execute("update client_states set hazard=%s where id=%s", (value, current["state_id"]))
            if rng.random() < value:
                await self._transition(current, ClientState.CHURN_INTENT, at, "timer", hazard=value)
        await self.conn.execute(
            "update behavior_runtime set next_hazard_sim=%s where run_id=%s and client_id=%s",
            (self.next_tick(at), run, client),
        )

    async def _complaint(
        self, current: Any, operation_id: int, at: dt.datetime, rng: SimRng, *, parent: int | None = None
    ) -> int:
        operation = await self.one(
            "select o.*,ci.name_ru city,c.region_code from operations o join clients c on c.id=o.client_id "
            "join cities ci on ci.id=c.city_id where o.id=%s and o.run_id=%s and o.client_id=%s",
            (operation_id, current["run_id"], current["client_id"]),
        )
        if operation is None:
            raise ValueError("нет причинной операции для complaint")
        params = PsychotypeParams.model_validate(current["params_snapshot"])
        allowed = current["policy_snapshot"]["complaint"]["eligible_inbound_channels"]
        weights = {key: float(value.root) for key, value in params.channel_weights.items() if key in allowed}
        denominator = sum(weights.values())
        if denominator <= 0:
            raise ValueError("нет разрешённого входящего канала complaint")
        channel = rng.weighted({key: value / denominator for key, value in weights.items()})
        textgen = TextGen(rng)
        generated = textgen.generate(
            "tech_fault",
            operation["product_code"],
            psychotype=current["psychotype_code"],
            city=operation["city"],
            channel=channel,
        )
        await self.conn.execute(
            "insert into ingest_sources(code,kind,channel_code,enabled,is_external) values('behavior_param','rest','chat',false,false) on conflict(code) do nothing"
        )
        result = await create_signal(
            self.conn,
            {
                "external_id": f"behavior:{current['run_id']}:{current['client_id']}:{current['episode_no']}:{operation_id}:{parent or 0}",
                "channel": channel,
                "client": {"client_id": current["client_id"]},
                "text": generated.text,
                "timestamp": at.isoformat(),
                "geo": {"source": "client_profile", "region_code": operation["region_code"]},
                "origin": "sim",
                "meta": {
                    "source_operation_id": operation_id,
                    "source_fault_id": operation["fault_id"],
                    "parent_signal_id": parent,
                    "behavior_policy_hash": current["policy_hash"],
                    "behavior_episode": current["episode_no"],
                    "template_id": generated.gold.get("template_id"),
                },
            },
            source_code="behavior_param",
            run_id=current["run_id"],
            sim_time=at,
        )
        if result["status"] != "accepted":
            raise ValueError("behavior complaint не принят normalizer; TX должна быть отменена")
        signal_id = result["signal_id"]
        self.generated_signals += 1
        await self.conn.execute("update signals set lang=%s where id=%s", (generated.gold["language"], signal_id))
        if current["first_complaint_sim"] is None:
            await self.conn.execute(
                "update behavior_runtime set first_complaint_sim=%s,next_hazard_sim=%s where run_id=%s and client_id=%s",
                (at, self.next_tick(at), current["run_id"], current["client_id"]),
            )
        await self._transition(current, ClientState.WAITING, at, "signal_sent", links={"signal_id": signal_id})
        await self._schedule(current, "repeat", signal_id, at + dt.timedelta(minutes=current["first_response_min"]))
        return int(signal_id)

    @staticmethod
    def pinned_policy(current: dict[str, Any]) -> DemoPolicy:
        snapshot = json.dumps(current["policy_snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(snapshot.encode()).hexdigest() != current["policy_hash"]:
            raise ValueError("pinned policy checksum нарушен")
        return DemoPolicy(current["policy_hash"], snapshot, current["policy_source_sha256"])

    async def _notification(self, evidence: Any) -> None:
        current = await self.episode(evidence["run_id"], evidence["client_id"])
        if (
            current is None
            or current["state"] == ClientState.CHURNED.value
            or evidence["observed_sim"] < current["opened_sim"]
        ):
            return
        observations = await notification_observations(self.conn, current, evidence["source_id"])
        notice = await self.one("select signal_id,incident_id from notifications where id=%s", (evidence["source_id"],))
        links = {key: value for key, value in (notice or {}).items() if value is not None}
        links["notification_id"] = evidence["source_id"]
        await self._care(current, observations, evidence["observed_sim"], "agent_reply", links=links)

    async def _care(
        self,
        current: Any,
        observations: tuple[CareObservation, ...],
        at: dt.datetime,
        trigger: str,
        *,
        links: dict[str, int] | None = None,
    ) -> Any:
        if not observations or at < current["opened_sim"]:
            return current
        policy = self.pinned_policy(current)
        params = PsychotypeParams.model_validate(current["params_snapshot"])
        if params.care_weights is None:
            raise ValueError("pinned care weights отсутствуют")
        weights = params.care_weights.model_dump(exclude_none=True)
        before = load_care(current["care_snapshot"])
        care = before
        context = CareContext(current["opened_sim"], current["first_complaint_sim"], current["first_response_min"])
        for observation in observations:
            result = evaluate_care(care, observation, context=context, policy=policy.care, weights=weights)
            care = result.state
        await self.conn.execute(
            "update behavior_runtime set care_snapshot=%s,sla_breached=%s where run_id=%s and client_id=%s",
            (Jsonb(dump_care(care)), care.sla_breached, current["run_id"], current["client_id"]),
        )
        state = ClientState(current["state"])
        if current["closed_sim"] is not None:
            state = ClientState.RETAINED if result.score >= policy.spec["retained_threshold"] else ClientState.SATISFIED
        if care.tone_violated and not before.tone_violated:
            trigger = "tone_violation"
        # Source timestamp остаётся в notification/event; поздняя доставка facts
        # не должна двигать историю состояний назад через уже записанный переход.
        effect = max(at, current["since_sim"])
        return await self._transition(current, state, effect, trigger, score=float(result.score), links=links)

    async def _twin(self, evidence: Any, at: dt.datetime) -> None:
        current = await self.episode(evidence["run_id"], evidence["client_id"])
        if current is None or current["closed_sim"] is not None:
            return
        reaction = await self.one(
            "select * from client_reactions where id=%s and run_id=%s and client_id=%s",
            (evidence["source_id"], evidence["run_id"], evidence["client_id"]),
        )
        if reaction is None or not await related(
            self.conn, current, signal_id=reaction["signal_id"], incident_id=reaction["incident_id"]
        ):
            return
        # Реальный child определяется по idempotency identity producer, а не
        # соседству timestamp. Observation без опубликованного текста не создаёт
        # фиктивный repeat и не переводит клиента в новый waiting.
        when = max(at, current["since_sim"])
        if reaction["reaction"] in ("asks_again", "escalates"):
            child = await self.one(
                "select s.id from ingest_messages m join signals s on s.id=m.signal_id "
                "where m.source_code='client_twin' and m.external_id=%s and m.status='accepted' and m.run_id=%s "
                "and s.run_id=%s and s.client_id=%s and s.parent_signal_id=%s",
                (
                    f"twin:{reaction['notification_id']}",
                    current["run_id"],
                    current["run_id"],
                    current["client_id"],
                    reaction["signal_id"],
                ),
            )
            if child is not None and await self._count_repeat(current, child["id"], when):
                if current["state"] == ClientState.CHURN_INTENT.value:
                    current = await self._transition(
                        current, ClientState.CHURN_INTENT, when, "signal_sent", links={"signal_id": child["id"]}
                    )
                else:
                    current = await self._transition(
                        current,
                        ClientState(reaction["reaction"]),
                        when,
                        "agent_reply",
                        links={"signal_id": child["id"]},
                    )
                    current = await self._transition(
                        current, ClientState.WAITING, when, "signal_sent", links={"signal_id": child["id"]}
                    )
        native = (
            await self.one(
                "select output from agent_steps where run_id=%s and node='twin_react' order by seq desc limit 1",
                (reaction["agent_run_id"],),
            )
            if reaction["agent_run_id"] is not None
            else None
        )
        explicit = native is not None and native["output"].get("churn_intent") is True
        if (reaction["reaction"] == "churn_intent" or explicit) and current["state"] != ClientState.CHURN_INTENT.value:
            await self._transition(current, ClientState.CHURN_INTENT, when, "agent_reply")

    async def _sla(self, evidence: Any, at: dt.datetime) -> None:
        current = await self.episode(evidence["run_id"], evidence["client_id"])
        if current is None or at < current["opened_sim"]:
            return
        event = await self.one(
            "select event_type,payload from sim_events where id=%s and run_id=%s",
            (evidence["source_id"], evidence["run_id"]),
        )
        if event is None or event["event_type"] not in (
            "sla.breached",
            "sla.report_missing",
            "sla.first_response_overdue",
        ):
            raise ValueError("исходный SLA breach отсутствует")
        payload = event["payload"]
        if not await related(
            self.conn, current, signal_id=payload.get("signal_id"), incident_id=payload.get("incident_id")
        ):
            return
        links = {key: payload[key] for key in ("signal_id", "incident_id") if payload.get(key) is not None}
        await self._care(current, (SlaEvidence(evidence["source_id"], at, True, True),), at, "sla_breach", links=links)

    async def _resolution(self, evidence: Any, at: dt.datetime) -> None:
        current = await self.episode(evidence["run_id"], evidence["client_id"])
        if current is None or current["closed_sim"] is not None or at < current["opened_sim"]:
            return
        # Для каждого actual cause требуется известный resolved incident; отсутствие
        # связи не превращается в inferred resolution. Открытый fault тоже блокирует.
        missing = await self.one(
            "select 1 from behavior_causes b where b.run_id=%s and b.client_id=%s and b.episode_no=%s and ("
            "(b.fault_id is not null and not exists(select 1 from faults f where f.id=b.fault_id and f.run_id=b.run_id and f.resolved_sim<=%s)) "
            "or not exists(select 1 from incidents i where i.run_id=b.run_id and i.status in ('resolved','closed') "
            "and coalesce(i.resolved_sim,i.closed_sim)<=%s and ((b.fault_id is not null and i.fault_id=b.fault_id) "
            "or exists(select 1 from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=i.id and s.run_id=b.run_id "
            "and s.client_id=b.client_id and (s.source_operation_id=b.operation_id or (b.fault_id is not null and s.source_fault_id=b.fault_id)))))) limit 1",
            (current["run_id"], current["client_id"], current["episode_no"], at, at),
        )
        if missing is not None:
            return
        async with self.conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(
                "select source_id from behavior_receipts where run_id=%s and client_id=%s and source_kind='signal' and action=%s order by source_id",
                (current["run_id"], current["client_id"], f"cause:{current['episode_no']}"),
            )
            signal_causes = await cur.fetchall()
        for (source,) in signal_causes:
            if not await signal_resolved(self.conn, current, source, at):
                return
        policy = self.pinned_policy(current)
        target = (
            ClientState.RETAINED
            if float(current["care_score"] or 0) >= policy.spec["retained_threshold"]
            else ClientState.SATISFIED
        )
        await self._transition(
            current, target, max(at, current["since_sim"]), "closure", links={"incident_id": evidence["source_id"]}
        )
        await self.conn.execute(
            "update behavior_runtime set closed_sim=%s where run_id=%s and client_id=%s",
            (at, current["run_id"], current["client_id"]),
        )
        from app.sim.behavior.cancellation import cancel_pending

        await cancel_pending(self.conn, current, evidence, at=at, observed_at=self.cancellation_observed_at)

    async def _agent_intent(self, evidence: Any, at: dt.datetime, rng: SimRng) -> None:
        from app.sim.behavior.signals import canonical

        intent = await self.one(
            "select x.* from behavior_agent_intents x join signals s on s.id=x.signal_id "
            "and s.run_id=x.run_id and s.client_id=x.client_id join agent_runs a on a.id=x.agent_run_id "
            "and a.sim_run_id=x.run_id and a.signal_id=x.signal_id where x.id=%s and x.run_id=%s and x.client_id=%s",
            (evidence["source_id"], evidence["run_id"], evidence["client_id"]),
        )
        if intent is None:
            return
        signal = await canonical(self.conn, intent["run_id"], intent["client_id"], intent["signal_id"])
        if signal is None:
            return  # Свободный state request/gold не подтверждает complaint.
        current = await self.episode(intent["run_id"], intent["client_id"])
        if current is not None and current["state"] == ClientState.CHURNED.value:
            return
        fresh = await self.store.receipt(
            run_id=intent["run_id"],
            client_id=intent["client_id"],
            source_kind="signal",
            source_id=signal["id"],
            action="affect",
            at=at,
        )
        if current is None or current["closed_sim"] is not None:
            if not fresh:
                return
            current, _, _ = await self._open(
                intent["run_id"], intent["client_id"], signal["received_sim"], rng, current, source_signal=signal["id"]
            )
        member = await self.store.receipt(
            run_id=intent["run_id"],
            client_id=intent["client_id"],
            source_kind="signal",
            source_id=signal["id"],
            action=f"cause:{current['episode_no']}",
            at=at,
        )
        if not member:
            return
        from app.sim.behavior.runtime import capture_signal_case

        await capture_signal_case(self.conn, intent["run_id"], intent["client_id"], signal["id"])
        when = max(at, current["since_sim"])
        if current["first_complaint_sim"] is None:
            first = max(signal["received_sim"], current["opened_sim"])
            await self.conn.execute(
                "update behavior_runtime set first_complaint_sim=%s,next_hazard_sim=%s where run_id=%s and client_id=%s",
                (first, self.next_tick(when), intent["run_id"], intent["client_id"]),
            )
            from app.sim.behavior.cancellation import cancel_pending

            await cancel_pending(
                self.conn,
                current,
                evidence,
                at=when,
                observed_at=self.cancellation_observed_at,
                canonical_signal_id=signal["id"],
            )
        flags = signal["classification"].get("flags") or []
        if "repeat" in flags:
            await self._count_repeat(current, signal["id"], when)
        selected = (
            ClientState.CHURN_INTENT
            if "churn_intent" in flags or current["state"] == ClientState.CHURN_INTENT.value
            else ClientState.WAITING
        )
        current = await self._transition(current, selected, when, "signal_sent", links={"signal_id": signal["id"]})
        await self._schedule(
            current,
            "repeat",
            signal["id"],
            max(when, signal["received_sim"] + dt.timedelta(minutes=current["first_response_min"])),
        )
