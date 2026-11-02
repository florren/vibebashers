"""Сценарий6: native journal transitions; модель/HTTP вне phase TX."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import psycopg

from app.agent import proactive
from app.ingest.normalizer import create_signal, from_api_signal
from app.sim.behavior.runtime import require_run
from app.sim.behavior.store import BehaviorStore
from app.sim.events import EventBus
from app.sim.proactive_scenario import PREFIX, Case, ScriptedScenarioError, case, prepared, rows

if TYPE_CHECKING:
    from app.sim.engine import Simulator


async def emit(conn: psycopg.AsyncConnection[Any], context: Case, phase: str, at: dt.datetime, **facts: Any) -> None:
    record = context.prepared
    await EventBus(conn).emit(
        record.run_id,
        PREFIX + phase,
        {
            "event_type": PREFIX + phase,
            "version": 1,
            "scenario_id": context.spec.id,
            "script_sha256": record.payload["script_sha256"],
            "fault_id": record.payload["fault_id"],
            "prepared_event_id": record.id,
            **facts,
        },
        at,
        scenario_id=context.spec.id,
        correlation_id=record.correlation_id,
    )


async def locked(conn: psycopg.AsyncConnection[Any], run_id: int) -> tuple[Case, dt.datetime] | None:
    # В этой TX не берём Python Simulator lock и не вызываем модель.
    await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"scenario-proactive:{run_id}",))
    if await BehaviorStore(conn).current_effect_time(run_id) is None:
        return None
    owner = await rows(
        conn,
        "select st.sim_time from sim_state st join sim_runs r on r.id=st.current_run_id "
        "where st.id=1 and r.id=%s and r.kind='scenario' and r.status='paused' and not st.running for share of st",
        (run_id,),
    )
    if not owner:
        return None
    context = await case(conn, run_id)
    if context is None or "failed" in context.events or "completed" in context.events:
        return None
    await require_run(conn, run_id)
    return context, owner[0]["sim_time"]


async def fail(conn: psycopg.AsyncConnection[Any], run_id: int, reason: str) -> None:
    """Terminal diagnostic не меняет human choice/AR status и не ретраит LLM."""
    await conn.rollback()
    record = await prepared(conn, run_id)
    clock = await proactive.current_clock(conn, run_id)
    if record is None or clock is None:
        return
    await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"scenario-proactive:{run_id}",))
    current = await BehaviorStore(conn).current_effect_time(run_id)
    if current is None:
        return
    clock = await proactive.current_clock(conn, run_id)
    if clock is None:
        return
    await require_run(conn, run_id)
    if await rows(
        conn,
        "select 1 from sim_events where run_id=%s and event_type=any(%s)",
        (run_id, [PREFIX + "failed", PREFIX + "completed"]),
    ):
        return
    from app.contracts.registry import validate

    # Original hash сохраняется и при changed YAML, не присваиваем новый.
    payload = {k: v for k, v in record.payload.items() if k != "operation_ids"}
    payload.update(event_type=PREFIX + "failed", prepared_event_id=record.id, reason=reason)
    if validate(payload, "sim/scenario_proactive"):
        payload["reason"] = "inconsistent_evidence"
    await EventBus(conn).emit(
        run_id,
        PREFIX + "failed",
        payload,
        clock[1],
        scenario_id=record.payload["scenario_id"],
        correlation_id=record.correlation_id,
    )
    await conn.commit()


async def native_anchor(
    conn: psycopg.AsyncConnection[Any], context: Case, *, active: bool = True
) -> dict[str, Any] | None:
    found = await rows(
        conn,
        "select s.*,s.channel_code as channel from signals s join ingest_messages m on m.signal_id=s.id "
        "where s.run_id=%s and m.run_id=s.run_id and m.source_code=%s and m.status='accepted' and m.external_id=%s",
        (
            context.prepared.run_id,
            proactive.SOURCE,
            f"fault-{context.prepared.run_id}-{context.prepared.payload['fault_id']}",
        ),
    )
    if not found:
        return None
    if (
        len(found) != 1
        or not proactive.is_service(found[0])
        or found[0]["client_id"] is not None
        or found[0]["source_fault_id"] != context.prepared.payload["fault_id"]
    ):
        raise ScriptedScenarioError("inconsistent_evidence")
    if active:
        valid = await proactive.service_scope(conn, found[0], context.prepared.run_id, for_effect=True)
    else:
        # Read-only historical report — native completion as_of, никогда
        # authority для producer/recovery и никогда чужой current clock.
        valid = await proactive.fault_scope(
            conn, context.prepared.run_id, context.prepared.payload["fault_id"], context.observed_at
        )
    if not valid:
        raise ScriptedScenarioError("inconsistent_evidence")
    return found[0]


async def notice_evidence(conn: psycopg.AsyncConnection[Any], context: Case, anchor: int) -> list[dict[str, Any]]:
    found = await rows(
        conn,
        "select n.id,n.client_id,n.sent_sim,n.status,b.first_complaint_sim from notifications n "
        "join behavior_runtime b on b.run_id=n.run_id and b.client_id=n.client_id "
        "where n.run_id=%s and n.signal_id=%s and n.template_code='proactive_fault' "
        "and n.recipient_type='client' order by n.id",
        (context.prepared.run_id, anchor),
    )
    people = {person["client_id"] for person in context.operations}
    delivered = [entry for entry in found if entry["status"] in ("sent", "delivered")]
    if any(
        entry["client_id"] not in people
        or entry["sent_sim"] is None
        or not context.initial_at <= entry["sent_sim"] <= context.complaints_at
        or (entry["first_complaint_sim"] is not None and entry["sent_sim"] >= entry["first_complaint_sim"])
        for entry in delivered
    ) or len({entry["client_id"] for entry in delivered}) != len(delivered):
        raise ScriptedScenarioError("inconsistent_evidence")
    return delivered


async def early_complaint(conn: psycopg.AsyncConnection[Any], context: Case) -> bool:
    from app.sim.behavior.signals import canonical

    run_id = context.prepared.run_id
    people = [person["client_id"] for person in context.operations]
    if await rows(
        conn,
        "select 1 from behavior_runtime where run_id=%s and client_id=any(%s) and first_complaint_sim is not null limit 1",
        (run_id, people),
    ):
        return True
    # Classifier receipt уже может быть committed между paused owner ticks.
    # Native owner canonical(), а не guessed sentiment/любой внешний input.
    inputs = await rows(
        conn,
        "select s.id,s.client_id from signals s where s.run_id=%s and s.client_id=any(%s) "
        "and s.origin is distinct from 'proactive' and (s.source_operation_id=any(%s) or exists("
        "select 1 from incident_signals l join incidents i on i.id=l.incident_id where l.signal_id=s.id "
        "and i.run_id=s.run_id and i.fault_id=%s)) order by s.id",
        (
            run_id,
            people,
            [person["operation_id"] for person in context.operations],
            context.prepared.payload["fault_id"],
        ),
    )
    for signal in inputs:
        if await canonical(conn, run_id, signal["client_id"], signal["id"]) is not None:
            return True
    return False


async def ar_state(conn: psycopg.AsyncConnection[Any], run_id: int, signals: list[int]) -> list[dict[str, Any]]:
    return await rows(
        conn,
        "select s.id signal_id,a.id,a.outcome,a.interrupted_at,a.started_at from signals s left join lateral "
        "(select ar.id,ar.outcome,ar.interrupted_at,ar.started_at from agent_runs ar "
        "where ar.signal_id=s.id and ar.sim_run_id=s.run_id and ar.kind='agent' order by ar.id desc limit 1) a on true "
        "where s.run_id=%s and s.id=any(%s) order by s.id",
        (run_id, signals),
    )


async def advance(conn: psycopg.AsyncConnection[Any], sim: Simulator) -> list[int]:
    """Один bounded переход. Caller запускает graph только после commit.

    Native clock target делает повтор идемпотентным; incomplete/unknown не success.
    """
    clock = await proactive.current_clock(conn)
    if clock is None or sim.run_id != clock[0]:
        return []
    run_id = clock[0]
    if await prepared(conn, run_id) is None:
        return []
    try:
        scope = await locked(conn, run_id)
        if scope is None:
            return []
        context, at = scope
        if at == context.prepared.at:
            await conn.commit()
            await sim.prepared_step(run_id, context.prepared.at, context.initial_at)
            return []
        fault = await proactive.fault_scope(conn, run_id, context.prepared.payload["fault_id"], at)
        if fault is None or fault["affected_count"] != len(context.operations):
            raise ScriptedScenarioError("fault_resolved")
        anchor = await native_anchor(conn, context)
        if anchor is None:
            if at != context.initial_at:
                raise ScriptedScenarioError("phase_clock_changed")
            return []
        states = await ar_state(conn, run_id, [anchor["id"]])
        if not states or states[0]["outcome"] == "failed":
            raise ScriptedScenarioError("service_graph_failed")
        if "notified" in context.events and (
            context.events["notified"]["payload"]["anchor_signal_id"] != anchor["id"]
            or context.events["notified"]["payload"]["agent_run_id"] != states[0]["id"]
        ):
            raise ScriptedScenarioError("inconsistent_evidence")
        if "notified" not in context.events:
            if await early_complaint(conn, context):
                raise ScriptedScenarioError("early_complaint")
            notices = await notice_evidence(conn, context, anchor["id"])
            if len(notices) < context.spec.script.minimum_notices:
                return []
            if at != context.initial_at:
                raise ScriptedScenarioError("phase_clock_changed")
            await emit(
                conn,
                context,
                "notified",
                at,
                anchor_signal_id=anchor["id"],
                agent_run_id=states[0]["id"],
                notification_ids=[entry["id"] for entry in notices],
            )
            await conn.commit()
            return []
        if "complaints" not in context.events:
            if at not in (context.initial_at, context.complaints_at):
                raise ScriptedScenarioError("phase_clock_changed")
            if at == context.initial_at:
                await conn.commit()
                await sim.prepared_step(run_id, context.initial_at, context.complaints_at)
                return []
            notices = await notice_evidence(conn, context, anchor["id"])
            if {entry["id"] for entry in notices} != set(context.events["notified"]["payload"]["notification_ids"]):
                raise ScriptedScenarioError("inconsistent_evidence")
            notified = {entry["client_id"] for entry in notices}
            ordered = sorted(
                context.operations, key=lambda person: (person["client_id"] in notified, person["client_id"])
            )
            complaint_ids = []
            for index, person in enumerate(ordered[: context.spec.script.complaints]):
                template = context.spec.complaint_templates[index % len(context.spec.complaint_templates)]
                message = from_api_signal(
                    {"client_id": person["client_id"], "channel_code": template.channel.value, "text": template.text}
                )
                message.update(origin="scenario", external_id=f"scenario-proactive-{run_id}-{person['operation_id']}")
                message["meta"].update(
                    scenario_id=context.spec.id,
                    source_operation_id=person["operation_id"],
                    source_fault_id=context.prepared.payload["fault_id"],
                )
                result = await create_signal(conn, message, source_code="api", run_id=run_id, sim_time=at)
                if result["status"] not in ("accepted", "duplicate") or result.get("signal_id") is None:
                    raise ScriptedScenarioError("inconsistent_evidence")
                complaint_ids.append(int(result["signal_id"]))
            await emit(
                conn,
                context,
                "complaints",
                at,
                notified_event_id=context.events["notified"]["id"],
                complaint_signal_ids=complaint_ids,
            )
            await conn.commit()
            return complaint_ids
        complaint_ids = [int(value) for value in context.events["complaints"]["payload"]["complaint_signal_ids"]]
        await journal_inputs(conn, context)
        states = await ar_state(conn, run_id, complaint_ids)
        if len(states) != context.spec.script.complaints or any(state["outcome"] == "failed" for state in states):
            raise ScriptedScenarioError("customer_graph_failed")
        if any(state["outcome"] is None for state in states):
            return complaint_ids
        if at == context.complaints_at:
            await conn.commit()
            await sim.prepared_step(run_id, context.complaints_at, context.observed_at)
            return complaint_ids
        if at != context.observed_at:
            raise ScriptedScenarioError("phase_clock_changed")
        linked = await rows(
            conn,
            "select distinct i.id,i.mass_impact,e.affected_count from incidents i join incident_economics e on e.incident_id=i.id join incident_signals l on l.incident_id=i.id where i.run_id=%s and i.fault_id=%s and l.signal_id=any(%s)",
            (run_id, context.prepared.payload["fault_id"], complaint_ids),
        )
        if (
            len(linked) != 1
            or linked[0]["mass_impact"] != len(context.operations)
            or linked[0]["affected_count"] != len(context.operations)
        ):
            raise ScriptedScenarioError("inconsistent_evidence")
        count = await rows(
            conn,
            "select count(distinct signal_id) n from incident_signals where incident_id=%s and signal_id=any(%s)",
            (linked[0]["id"], complaint_ids),
        )
        if count[0]["n"] != context.spec.script.complaints:
            raise ScriptedScenarioError("inconsistent_evidence")
        notices = await notice_evidence(conn, context, anchor["id"])
        care = await rows(
            conn,
            "select count(*) n from behavior_runtime b join client_states c on c.id=b.state_id where b.run_id=%s and b.client_id=any(%s) and c.care_score>0",
            (run_id, [entry["client_id"] for entry in notices]),
        )
        if care[0]["n"] < context.spec.script.minimum_notices:
            raise ScriptedScenarioError("inconsistent_evidence")
        await emit(
            conn,
            context,
            "completed",
            at,
            notified_event_id=context.events["notified"]["id"],
            complaints_event_id=context.events["complaints"]["id"],
            incident_id=linked[0]["id"],
            care_positive=care[0]["n"],
        )
        await conn.commit()
        return []
    except ScriptedScenarioError as error:
        await fail(conn, run_id, error.code)
        return []


async def journal_inputs(conn: psycopg.AsyncConnection[Any], context: Case, *, active: bool = True) -> list[int]:
    """Private recovery inputs только из native producer/typed journal, не ingestion meta."""
    anchor = await native_anchor(conn, context, active=active)
    if "notified" in context.events:
        native = context.events["notified"]["payload"]
        if (
            anchor is None
            or anchor["id"] != native["anchor_signal_id"]
            or not await rows(
                conn,
                "select 1 from agent_runs where id=%s and kind='agent' and sim_run_id=%s and signal_id=%s",
                (native["agent_run_id"], context.prepared.run_id, anchor["id"]),
            )
        ):
            raise ScriptedScenarioError("inconsistent_evidence")
    ids = [int(anchor["id"])] if anchor else []
    event = context.events.get("complaints")
    if event is None:
        return ids
    complaints = [int(value) for value in event["payload"]["complaint_signal_ids"]]
    found = await rows(
        conn,
        "select s.id,s.client_id,s.source_operation_id,s.source_fault_id,s.received_sim,s.origin,"
        "m.external_id,m.payload,m.source_code,m.status from signals s join ingest_messages m on m.signal_id=s.id "
        "where s.run_id=%s and m.run_id=s.run_id and s.id=any(%s)",
        (context.prepared.run_id, complaints),
    )
    by_id = {entry["id"]: entry for entry in found}
    operations = {entry["operation_id"]: entry for entry in context.operations}
    if (
        len(found) != len(complaints)
        or set(by_id) != set(complaints)
        or len({entry["client_id"] for entry in found}) != len(complaints)
    ):
        raise ScriptedScenarioError("inconsistent_evidence")
    for index, signal in enumerate(complaints):
        entry = by_id[signal]
        operation = operations.get(entry["source_operation_id"])
        template = context.spec.complaint_templates[index % len(context.spec.complaint_templates)]
        if (
            operation is None
            or operation["client_id"] != entry["client_id"]
            or entry["source_fault_id"] != context.prepared.payload["fault_id"]
            or entry["received_sim"] != context.complaints_at
            or entry["origin"] != "scenario"
            or entry["source_code"] != "api"
            or entry["status"] != "accepted"
            or entry["external_id"] != f"scenario-proactive-{context.prepared.run_id}-{entry['source_operation_id']}"
            or entry["payload"].get("text") != template.text
            or entry["payload"].get("channel") != template.channel.value
        ):
            raise ScriptedScenarioError("inconsistent_evidence")
    return [*ids, *complaints]


async def evaluate(conn: psycopg.AsyncConnection[Any], scenario: dict[str, Any], run_id: int) -> dict[str, Any]:
    """Read-only evidence. Ни missing phase, ни unknown check не становится passed."""
    from app.sim import scenarios

    checks: list[dict[str, Any]] = []
    counts: dict[str, Any] = {"prevented_complaints": None, "prevention_basis": "not_modelled"}

    def check(code: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "ok": ok, "detail": detail})

    try:
        context = await case(conn, run_id)
        complete = context is not None and "completed" in context.events and "failed" not in context.events
        check("native_phases_completed", complete, "Только typed completed с native refs; queued/unknown не доставка")
        if context is None or not complete:
            return {"passed": False, "checks": checks, "counts": counts}
        await journal_inputs(conn, context, active=False)
        notified = context.events["notified"]["payload"]
        completed = context.events["completed"]["payload"]
        complaints = context.events["complaints"]["payload"]["complaint_signal_ids"]
        notices = await notice_evidence(conn, context, notified["anchor_signal_id"])
        people = [person["client_id"] for person in context.operations]
        first = await rows(
            conn,
            "select min(first_complaint_sim) at from behavior_runtime where run_id=%s and client_id=any(%s)",
            (run_id, people),
        )
        before_first = sum(entry["sent_sim"] < first[0]["at"] for entry in notices) if first[0]["at"] is not None else 0
        incidents = await rows(
            conn,
            "select i.id,i.mass_impact,e.affected_count from incidents i join incident_economics e on e.incident_id=i.id where i.id=%s and i.run_id=%s and i.fault_id=%s",
            (completed["incident_id"], run_id, context.prepared.payload["fault_id"]),
        )
        links = await rows(
            conn,
            "select count(distinct signal_id) n from incident_signals where incident_id=%s and signal_id=any(%s)",
            (completed["incident_id"], complaints),
        )
        care = await rows(
            conn,
            "select count(*) n from behavior_runtime b join client_states c on c.id=b.state_id where b.run_id=%s and b.client_id=any(%s) and c.care_score>0",
            (run_id, [entry["client_id"] for entry in notices]),
        )
        counts.update(
            affected=len(people),
            notified=len(notices),
            notified_before_first_complaint=before_first,
            complaints=len(complaints),
            deduplicated=links[0]["n"],
            care_positive=care[0]["n"],
            delivery_basis="native_sent_emulated_or_transport_delivery; не доказательство real Telegram",
        )
        check(
            "native_affected",
            len(people) == context.spec.fault.affected_clients,
            f"actual distinct clients: {len(people)}",
        )
        check(
            "native_delivery",
            before_first >= context.spec.script.minimum_notices
            and {entry["id"] for entry in notices} == set(notified["notification_ids"]),
            f"Sent/delivered строго до первой жалобы: {before_first}",
        )
        check(
            "native_care",
            care[0]["n"] >= context.spec.script.minimum_notices and care[0]["n"] == completed["care_positive"],
            f"Native owner care>0: {care[0]['n']}; Sent не равно prevented",
        )
        check(
            "native_economics",
            len(incidents) == 1
            and incidents[0]["mass_impact"] == len(people)
            and incidents[0]["affected_count"] == len(people),
            "Один same-fault incident и existing economics, без пересчёта/записи",
        )
        data = await scenarios._run_data(conn, run_id)
        counts.update(
            signals=len(data["signals"]), incidents=len(data["incidents"]), agent_runs=len(data["agent_runs"])
        )
        for key, expected in (scenario.get("expected") or {}).items():
            if key == "complaints":
                check(key, len(complaints) == expected, f"Native journal customer inputs: {len(complaints)}")
            elif key == "dedupe_to_one_incident":
                check(
                    key,
                    len(incidents) == 1 and links[0]["n"] == len(complaints) and bool(expected),
                    f"same-fault links: {links[0]['n']}",
                )
            elif key == "flag":
                check(
                    key,
                    expected in scenarios._all_flags(data),
                    f"existing graph flags: {sorted(scenarios._all_flags(data))}",
                )
            elif key == "preventive_notice":
                check(
                    key,
                    bool(expected) and before_first >= context.spec.script.minimum_notices,
                    "Native delivery timing, не counterfactual prevention",
                )
            elif key == "map_zone":
                # Existing route — SELECT-only producer, explicit run, no refresh
                # экономики/модели. Формулу/thresholds здесь не воспроизводим.
                import json

                from app.api.map import get_map_zones

                own_clock = await rows(
                    conn,
                    "select 1 from sim_state where id=1 and current_run_id=%s and sim_time=%s",
                    (run_id, context.observed_at),
                )
                if not own_clock:
                    counts["map_basis"] = "historical_unavailable"
                    check(
                        key,
                        False,
                        "unavailable/not_verified: existing map producer требует actual own completion clock; historical run/current не переключаются",
                    )
                    continue
                counts["map_basis"] = "native_completion_clock"
                response = await get_map_zones(run_id=str(run_id))
                zones = json.loads(bytes(response.body))["items"]
                regions = {person["region_code"] for person in context.operations}
                actual = {entry["zone"] for entry in zones if entry["region_code"] in regions}
                check(key, expected in actual, f"Existing map producer zones: {sorted(actual)}")
            else:
                check(key, False, "Scripted expectation не реализован; unknown не passed")
        return {"passed": all(entry["ok"] is True for entry in checks), "checks": checks, "counts": counts}
    except ScriptedScenarioError as error:
        check("native_evidence", False, error.code)
        return {"passed": False, "checks": checks, "counts": counts}
