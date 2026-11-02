"""T039: prepared native source сценария6; journal — факты, не очередь LLM.

Short caller TX/owner lock до записей. Между фазами нет удерживаемого model lock;
clock/model/effects принадлежат штатным Simulator, graph и behavior owner.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from app.agent import proactive
from app.contracts.enums import Channel, PaymentMethod, Product, System
from app.contracts.events.sim.op import OpType
from app.contracts.registry import load, validate
from app.ingest.normalizer import from_api_signal
from app.ingest.schemas import UnifiedMessage
from app.sim.behavior import runtime
from app.sim.behavior.store import BehaviorStore
from app.sim.events import EventBus

PREFIX = "scenario.proactive_"
_PHASE_SCHEMAS = load("sim/scenario_proactive")["oneOf"]
MAX_COHORT = _PHASE_SCHEMAS[0]["properties"]["operation_ids"]["maxItems"]
MAX_COMPLAINTS = _PHASE_SCHEMAS[2]["properties"]["complaint_signal_ids"]["maxItems"]


class ScriptedScenarioError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"Сценарий6: {code}. Проверьте prepared source/состояние; при недостатке cohort используйте demo."
        )


class FaultSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_code: str
    system: System
    affected_clients: int = Field(gt=0, le=MAX_COHORT)
    district: str
    expected_duration_min: int = Field(gt=0)


class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_code: Product
    op_type: OpType
    method: PaymentMethod
    system_path: list[System] = Field(min_length=1)
    amount_rub: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    # Только техническая failed operation, не платёжный prepared fixture.
    fee_amount: Decimal = Field(ge=0, le=0)


class ScriptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_mode: Literal["prepared_native"]
    initial_step_min: Decimal = Field(gt=0, allow_inf_nan=False)
    complaint_step_min: Decimal = Field(gt=0, allow_inf_nan=False)
    owner_observation_step_min: Decimal = Field(gt=0, allow_inf_nan=False)
    complaints: int = Field(gt=0, le=MAX_COMPLAINTS)
    minimum_notices: int = Field(gt=0, le=MAX_COHORT)


class ComplaintTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Channel
    text: str = Field(min_length=1)


class Plan(BaseModel):
    _source_sha256: str = PrivateAttr(default="")
    id: str
    fault: FaultSpec
    operation: OperationSpec
    script: ScriptSpec
    complaint_templates: list[ComplaintTemplate] = Field(min_length=1)

    @property
    def sha256(self) -> str:
        if self._source_sha256:
            return self._source_sha256
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def plan(scenario: dict[str, Any]) -> Plan | None:
    if "script" not in scenario:
        return None
    try:
        parsed = Plan.model_validate(scenario)
        raw = json.dumps(
            {k: v for k, v in scenario.items() if not k.startswith("_")},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        parsed._source_sha256 = hashlib.sha256(raw.encode()).hexdigest()
        for template in parsed.complaint_templates:
            UnifiedMessage.model_validate(
                from_api_signal({"channel_code": template.channel.value, "text": template.text})
            )
        # Размер case задан data, protocol bounded schema проверяет совместимость.
        sample = {
            "event_type": PREFIX + "prepared",
            "version": 1,
            "scenario_id": parsed.id,
            "script_sha256": parsed.sha256,
            "fault_id": 1,
            "operation_ids": list(range(1, parsed.fault.affected_clients + 1)),
        }
        if validate(sample, "sim/scenario_proactive"):
            raise ScriptedScenarioError("unsupported_cohort")
        for phase, evidence in (
            (
                "notified",
                {
                    "prepared_event_id": 1,
                    "agent_run_id": 1,
                    "anchor_signal_id": 1,
                    "notification_ids": list(range(1, parsed.script.minimum_notices + 1)),
                },
            ),
            (
                "complaints",
                {
                    "prepared_event_id": 1,
                    "notified_event_id": 1,
                    "complaint_signal_ids": list(range(1, parsed.script.complaints + 1)),
                },
            ),
        ):
            probe = {k: value for k, value in sample.items() if k != "operation_ids"}
            probe.update(event_type=PREFIX + phase, **evidence)
            if validate(probe, "sim/scenario_proactive"):
                raise ScriptedScenarioError("unsupported_phase_count")
        if not 0 < parsed.script.complaints <= parsed.fault.affected_clients:
            raise ScriptedScenarioError("unsupported_complaints")
        # Не вводим другой clock path: каждый target — существующий atomic chunk.
        from app.sim.engine import MAX_BATCH_MIN

        for minutes in (
            parsed.script.initial_step_min,
            parsed.script.complaint_step_min,
            parsed.script.owner_observation_step_min,
        ):
            if minutes > MAX_BATCH_MIN or dt.timedelta(minutes=float(minutes)) <= dt.timedelta(0):
                raise ScriptedScenarioError("unsupported_script_timing")
        dt.timedelta(minutes=parsed.fault.expected_duration_min)
        return parsed
    except (ValidationError, OverflowError, ValueError, TypeError) as exc:
        if isinstance(exc, ScriptedScenarioError):
            raise
        raise ScriptedScenarioError("invalid_script") from None


@dataclass(frozen=True)
class Prepared:
    id: int
    run_id: int
    at: dt.datetime
    payload: dict[str, Any]
    correlation_id: uuid.UUID


async def rows(conn: psycopg.AsyncConnection[Any], query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return await proactive.rows(conn, query, args)


async def prepared(conn: psycopg.AsyncConnection[Any], run_id: int) -> Prepared | None:
    found = await rows(
        conn,
        "select id,payload,sim_time,correlation_id from sim_events where run_id=%s and event_type=%s order by id",
        (run_id, PREFIX + "prepared"),
    )
    if not found:
        return None
    if (
        len(found) != 1
        or validate(found[0]["payload"], "sim/scenario_proactive")
        or found[0]["payload"].get("event_type") != PREFIX + "prepared"
    ):
        raise ScriptedScenarioError("inconsistent_evidence")
    row = found[0]
    return Prepared(row["id"], run_id, row["sim_time"], row["payload"], row["correlation_id"])


async def preflight(conn: psycopg.AsyncConnection[Any], spec: Plan, *, lock: bool = False) -> list[dict[str, Any]]:
    await proactive.configuration(conn)
    codes = await rows(conn, "select system_code,product_code from error_codes where code=%s", (spec.fault.error_code,))
    if (
        len(codes) != 1
        or codes[0]["system_code"] != spec.fault.system.value
        or (codes[0]["product_code"] is not None and codes[0]["product_code"] != spec.operation.product_code.value)
        or spec.fault.system not in spec.operation.system_path
    ):
        raise ScriptedScenarioError("inconsistent_catalog")
    cohort = await rows(
        conn,
        "select c.id,c.region_code,c.segment_code,c.consents,c.contacts,p.params from clients c "
        "join regions r on r.code=c.region_code join psychotypes p on p.code=c.psychotype_code "
        "where c.is_active and r.district_code=%s and exists(select 1 from client_products cp "
        "where cp.client_id=c.id and cp.product_code=%s and cp.status='active') "
        "order by c.id limit %s" + (" for share of c" if lock else ""),
        (spec.fault.district, spec.operation.product_code.value, spec.fault.affected_clients),
    )
    if len(cohort) != spec.fault.affected_clients:
        raise ScriptedScenarioError("insufficient_cohort")
    eligible = [
        person
        for person in cohort
        if proactive.preferred_channel(person)
        and not (proactive.preferred_channel(person) == "email" and (person["consents"] or {}).get("email") is False)
    ]
    if len(eligible) < spec.script.minimum_notices:
        raise ScriptedScenarioError("insufficient_consents")
    if lock:
        products = await rows(
            conn,
            "select client_id from client_products where client_id=any(%s) and product_code=%s and status='active' for share",
            ([person["id"] for person in cohort], spec.operation.product_code.value),
        )
        if {row["client_id"] for row in products} != {person["id"] for person in cohort}:
            raise ScriptedScenarioError("cohort_changed")
    from app.contracts.events.behavior.psychotype_params import PsychotypeParams

    earliest = min(PsychotypeParams.model_validate(person["params"]).complain_delay_min[0].root for person in cohort)
    window = spec.script.initial_step_min + spec.script.complaint_step_min + spec.script.owner_observation_step_min
    if window >= earliest:
        raise ScriptedScenarioError("script_overlaps_native_due")
    if window >= spec.fault.expected_duration_min:
        raise ScriptedScenarioError("script_overlaps_fault_window")
    return cohort


async def prepare(conn: psycopg.AsyncConnection[Any], run_id: int, spec: Plan) -> Prepared:
    """Caller держит Simulator owner lock; все native rows/journal одной short TX."""
    if conn.autocommit:
        BehaviorStore(conn).require_transaction()
    await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"scenario-proactive:{run_id}",))
    scope = await rows(
        conn,
        "select st.sim_time from sim_runs r join sim_state st on st.id=1 and st.current_run_id=r.id "
        "where r.id=%s and r.kind='scenario' and r.scenario_id=%s and r.status='paused' "
        "and st.running=false for share of r for update of st",
        (run_id, spec.id),
    )
    if len(scope) != 1:
        raise ScriptedScenarioError("owner_changed")
    at = scope[0]["sim_time"]
    existing = await prepared(conn, run_id)
    if existing:
        if existing.payload["script_sha256"] != spec.sha256:
            raise ScriptedScenarioError("script_changed")
        return existing
    policy = await runtime.effective_policy(conn, run_id, runtime.configured_policy())
    if policy is None:
        raise ScriptedScenarioError("behavior_owner_required")
    await runtime.prepare_run(conn, run_id, at, policy)
    cohort = await preflight(conn, spec, lock=True)
    fault = await rows(
        conn,
        "insert into faults(run_id,system_code,error_code,region_codes,started_sim) values(%s,%s,%s,%s,%s) returning id",
        (
            run_id,
            spec.fault.system.value,
            spec.fault.error_code,
            sorted({person["region_code"] for person in cohort}),
            at,
        ),
    )
    fid = fault[0]["id"]
    correlation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"T039:{run_id}:{fid}:{spec.sha256}")
    bus = EventBus(conn)
    await bus.emit(
        run_id,
        "fault.started",
        {
            "fault_id": fid,
            "system": spec.fault.system.value,
            "error_code": spec.fault.error_code,
            "region_codes": sorted({person["region_code"] for person in cohort}),
            "started_sim": at.isoformat(),
            "expected_duration_min": spec.fault.expected_duration_min,
            "impact_count": 0,
            "affected_clients": 0,
        },
        at,
        scenario_id=spec.id,
        correlation_id=correlation_id,
    )
    operation_ids = []
    for person in cohort:
        [op] = await rows(
            conn,
            "insert into operations(run_id,client_id,product_code,op_type,system_path,method,amount_rub,fee_amount,status,error_code,fault_id,started_sim,finished_sim) "
            "values(%s,%s,%s,%s,%s,%s,%s,0,'failed',%s,%s,%s,%s) returning id",
            (
                run_id,
                person["id"],
                spec.operation.product_code.value,
                spec.operation.op_type.value,
                [system.value for system in spec.operation.system_path],
                spec.operation.method.value,
                spec.operation.amount_rub,
                spec.fault.error_code,
                fid,
                at,
                at,
            ),
        )
        operation_ids.append(op["id"])
        await bus.emit(
            run_id,
            "op.failed",
            {
                "operation_id": op["id"],
                "client_id": person["id"],
                "segment": person["segment_code"],
                "region_code": person["region_code"],
                "product": spec.operation.product_code.value,
                "op_type": spec.operation.op_type.value,
                "system_path": [system.value for system in spec.operation.system_path],
                "method": spec.operation.method.value,
                "amount_rub": float(spec.operation.amount_rub),
                "fee_amount": 0,
                "status": "failed",
                "error_code": spec.fault.error_code,
                "fault_id": fid,
                "started_sim": at.isoformat(),
            },
            at,
            scenario_id=spec.id,
            correlation_id=correlation_id,
        )
    await conn.execute(
        "update faults set impact_count=(select count(*) from operations where run_id=%s and fault_id=%s),"
        "affected_clients=(select count(distinct client_id) from operations where run_id=%s and fault_id=%s) where id=%s",
        (run_id, fid, run_id, fid, fid),
    )
    await bus.emit(
        run_id,
        PREFIX + "prepared",
        {
            "version": 1,
            "scenario_id": spec.id,
            "script_sha256": spec.sha256,
            "fault_id": fid,
            "operation_ids": operation_ids,
        },
        at,
        scenario_id=spec.id,
        correlation_id=correlation_id,
    )
    result = await prepared(conn, run_id)
    assert result is not None
    return result
