"""T-256: пакетные customer facts текущего run, без вычисляющих writes/LLM."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.analytics.cabinet_scope import validate_run
from app.analytics.cx_index import Observation
from app.api.common import fetch_one
from app.contracts.enums import Flag, SignalType
from app.trace.store import Conn


@dataclass(frozen=True)
class MetricsScope:
    requested: str
    run_id: int | None
    now: dt.datetime
    current_missing: bool = False

    @property
    def since(self) -> dt.datetime:
        return self.now - dt.timedelta(hours=24)


async def metrics_scope(conn: Conn, requested: str) -> MetricsScope:
    """Метрики current-only; пустой pointer никогда не превращается в all."""
    validate_run(requested)
    state = await fetch_one(conn, "SELECT sim_time,current_run_id FROM sim_state WHERE id=1")
    if state is None:
        raise HTTPException(503, "Симуляционные часы не инициализированы")
    if requested == "all":
        scope = MetricsScope(requested, None, state["sim_time"])
    elif requested == "current":
        current = state["current_run_id"]
        scope = MetricsScope(requested, int(current) if current is not None else -1, state["sim_time"], current is None)
    else:
        rid = int(requested)
        if await fetch_one(conn, "SELECT id FROM sim_runs WHERE id=%s", (rid,)) is None:
            raise HTTPException(404, "Запуск не найден")
        scope = MetricsScope(requested, rid, state["sim_time"])
    if not scope.current_missing:
        await _validate_temporal_context(conn, scope)
    return scope


async def _validate_temporal_context(conn: Conn, scope: MetricsScope) -> None:
    """Защитная граница известных future evidence, не реконструкция истории.

    Отсутствие complaint receipt не доказывает публикацию классификации:
    положительные классификации не создают такой receipt. Корректность native
    start дополнительно требует upstream stale-controller fence (T-041).
    """
    run_filter = " AND id=%s" if scope.run_id is not None else ""
    receipt_filter = " AND run_id=%s" if scope.run_id is not None else ""
    args: list[Any] = [scope.now, scope.now]
    if scope.run_id is not None:
        args.append(scope.run_id)
    args.append(scope.now)
    if scope.run_id is not None:
        args.append(scope.run_id)
    conflict = await fetch_one(
        conn,
        f"""SELECT EXISTS (
          SELECT 1 FROM sim_runs WHERE (started_sim>%s OR finished_sim>%s) {run_filter}
        ) OR EXISTS (
          SELECT 1 FROM behavior_agent_intents WHERE observed_sim>%s {receipt_filter}
        ) AS conflict""",
        args,
    )  # noqa: S608 — predicates внутренние, scope и время параметризованы.
    assert conflict is not None
    if conflict["conflict"]:
        raise HTTPException(409, "temporal_context_conflict")


def _signal_selection(scope: MetricsScope, historical: bool) -> tuple[str, list[Any]]:
    run_sql = " AND f.run_id=%s" if scope.run_id is not None else ""
    args: list[Any] = [scope.since, scope.now, *([scope.run_id] if scope.run_id is not None else [])]
    if not historical:
        return (
            f"""selected AS MATERIALIZED (
              SELECT f.id,f.received_sim,f.channel_code,s.classification AS c
              FROM v_cabinet_signal_facts f JOIN signals s ON s.id=f.id
              WHERE f.received_sim>%s AND f.received_sim<=%s {run_sql}
            )""",
            args,
        )
    from app.economics.calibration import PIPELINE

    # churn_predicted_sim не является publication/observation time после awaitLLM.
    # Используем независимый observed receipt; без точного step pairing — unknown.
    return (
        f"""selected_ids AS MATERIALIZED (
          SELECT f.id,f.run_id,f.client_id,f.received_sim,f.channel_code FROM v_cabinet_signal_facts f
          WHERE f.received_sim>%s AND f.received_sim<=%s {run_sql}
        ), snapshots AS MATERIALIZED (
          SELECT a.id,a.signal_id,a.sim_run_id,count(st.id) AS steps,
            (array_agg(st.node ORDER BY st.seq DESC,st.id DESC))[1] AS node,
            (array_agg(st.output ORDER BY st.seq DESC,st.id DESC))[1] AS output
          FROM selected_ids x JOIN agent_runs a ON a.signal_id=x.id AND a.sim_run_id=x.run_id
            AND a.kind='agent' AND a.client_id=x.client_id
          LEFT JOIN agent_steps st ON st.run_id=a.id AND st.node IN ('classify','instant_decide')
            AND st.status IN ('ok','fallback') GROUP BY a.id
        ), receipt_candidates AS MATERIALIZED (
          SELECT x.id,bi.observed_sim,
            CASE WHEN z.steps=1 AND z.output->>'score_pipeline'=%s THEN
              CASE WHEN z.node='classify' THEN z.output ELSE z.output->'classification_snapshot' END END AS c,
            dense_rank() OVER(PARTITION BY x.id ORDER BY bi.observed_sim DESC) AS latest
          FROM selected_ids x JOIN behavior_agent_intents bi ON bi.signal_id=x.id
            AND bi.run_id=x.run_id AND bi.client_id=x.client_id AND bi.trigger='classifier:complaint'
            AND bi.requested_state='complaining' AND bi.incident_id IS NULL
          JOIN snapshots z ON z.id=bi.agent_run_id AND z.signal_id=x.id AND z.sim_run_id=x.run_id
          WHERE bi.observed_sim<=%s
        ), historical_classification AS (
          SELECT id,CASE WHEN count(*)=1 THEN min(c::text)::jsonb END AS c
          FROM receipt_candidates WHERE latest=1 GROUP BY id
        ), selected AS MATERIALIZED (
          SELECT x.id,x.received_sim,x.channel_code,h.c FROM selected_ids x
          LEFT JOIN historical_classification h ON h.id=x.id
        )""",
        [*args, PIPELINE, scope.now],
    )


async def signal_facts(conn: Conn, scope: MetricsScope, *, historical: bool = False) -> dict[str, Any]:
    """N/C/R и24rolling-hour buckets; raw default flags не являются классификацией."""
    selection, selection_args = _signal_selection(scope, historical)
    facts = await fetch_one(
        conn,
        f"""
        WITH {selection}, numeric_facts AS MATERIALIZED (
          SELECT *,CASE WHEN jsonb_typeof(c->'negativity')='number' THEN (c->>'negativity')::numeric END AS raw_n
          FROM selected
        ), scored AS MATERIALIZED (
          SELECT *,CASE WHEN raw_n BETWEEN 0 AND 100 AND raw_n=trunc(raw_n) THEN raw_n END AS negativity,
            CASE WHEN c->>'criticality' IN ('low','medium','high') THEN c->>'criticality' END AS criticality,
            CASE WHEN jsonb_typeof(c->'flags')='array' AND c->>'signal_type'=ANY(%s)
              AND c->>'criticality' IN ('low','medium','high') AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(c->'flags')='array' THEN c->'flags' ELSE '[]'::jsonb END) flag
                WHERE jsonb_typeof(flag)<>'string' OR (flag#>>'{{}}')<>ALL(%s)
              ) THEN c->'flags' ? 'churn_intent' END AS churn
          FROM numeric_facts
        ), channel_mix AS (
          SELECT channel_code,count(*) AS signals FROM selected GROUP BY channel_code
        ), bucket_counts AS (
          SELECT least(23,greatest(0,ceil(extract(epoch FROM(received_sim-%s::timestamptz))/3600)::int-1)) AS bucket,
            count(*) AS signals FROM selected GROUP BY 1
        ), flow AS (
          SELECT bucket,%s::timestamptz+bucket*interval '1 hour' AS starts_sim,
            %s::timestamptz+(bucket+1)*interval '1 hour' AS ends_sim,coalesce(n.signals,0) AS signals
          FROM generate_series(0,23) AS b(bucket) LEFT JOIN bucket_counts n USING(bucket) ORDER BY bucket
        ) SELECT count(*) AS total,count(negativity) AS negativity_known,avg(negativity) AS negativity_value,sum(negativity) AS negativity_sum,
          count(criticality) AS criticality_known,count(*) FILTER(WHERE criticality='high') AS criticality_high,
          count(churn) AS churn_known,count(*) FILTER(WHERE churn) AS churn_positive,
          (SELECT jsonb_agg(to_jsonb(m) ORDER BY m.channel_code) FROM channel_mix m) AS channel_mix,
          (SELECT jsonb_agg(to_jsonb(f) ORDER BY f.bucket) FROM flow f) AS flow
        FROM scored
        """,
        [
            *selection_args,
            [item.value for item in SignalType],
            [item.value for item in Flag],
            scope.since,
            scope.since,
            scope.since,
        ],
    )  # noqa: S608 — только внутренний predicate; все значения параметризованы.
    assert facts is not None
    total = int(facts["total"])
    components = {
        "negativity": Observation(
            float(facts["negativity_value"]) if facts["negativity_value"] is not None else None,
            int(facts["negativity_known"]),
            total,
        )
    }
    for code, numerator in (("criticality", "criticality_high"), ("churn", "churn_positive")):
        known = int(facts[code + "_known"])
        components[code] = Observation(100 * int(facts[numerator]) / known if known else None, known, total)
    return {
        "components": components,
        "channel_mix": facts["channel_mix"] or [],
        "flow": facts["flow"],
        "signals": total,
        "evidence": {
            "negativity_sum": int(facts["negativity_sum"]) if facts["negativity_sum"] is not None else None,
            "criticality_high": int(facts["criticality_high"]),
            "churn_positive": int(facts["churn_positive"]),
            "basis": "observed_classification_receipts" if historical else "recorded_classification",
        },
    }


def registered_sla_risk(row: dict[str, Any], now: dt.datetime) -> bool | None:
    """Registered indicator, не прогноз: unknown lifecycle не является нулём."""
    from app.analytics.cabinet_report import warning_current

    stage, due = row.get("stage_sim"), row.get("sla_due_sim")
    if (
        not isinstance(stage, dt.datetime)
        or stage.utcoffset() is None
        or not isinstance(due, dt.datetime)
        or due.utcoffset() is None
        or row.get("stage_status") != row.get("status")
        or stage > now
    ):
        return None
    if due < now or warning_current(row, now):
        return True
    if any(row.get(key) is not None for key in ("warning_event_id", "release_sim", "reopened_sim")):
        return None
    # Это отсутствие зарегистрированного случая в полной current-stage выборке,
    # а не доказательство отсутствия будущего/незарегистрированного риска.
    return False


async def sla_facts(conn: Conn, scope: MetricsScope) -> dict[str, Any]:
    """S: current open stock, current-lifecycle native warning либо просрочка."""
    from app.api.common import fetch_all
    from app.economics.dcltv import OPEN_STATUSES

    run_sql = " AND f.run_id=%s" if scope.run_id is not None else ""
    run_args = [scope.run_id] if scope.run_id is not None else []
    rows = await fetch_all(
        conn,
        f"""
        WITH selected AS MATERIALIZED (
          SELECT DISTINCT f.id FROM v_cabinet_incident_facts f
          WHERE f.created_sim<=%s AND f.status=ANY(%s) {run_sql}
        ), stages AS MATERIALIZED (
          SELECT DISTINCT ON(h.incident_id) h.incident_id,h.changed_sim,h.to_status
          FROM incident_status_history h JOIN selected x ON x.id=h.incident_id
          ORDER BY h.incident_id,h.changed_sim DESC,h.id DESC
        ), resets AS (
          SELECT h.incident_id,max(h.changed_sim) FILTER(WHERE h.from_status IS NOT NULL
            AND h.from_status<>ALL(%s) AND h.to_status=ANY(%s)) AS reopened_sim
          FROM incident_status_history h JOIN selected x ON x.id=h.incident_id GROUP BY h.incident_id
        ), releases AS (
          SELECT a.incident_id,max(a.action_sim) AS release_sim FROM team_actions a
          JOIN selected x ON x.id=a.incident_id JOIN incidents i ON i.id=x.id AND i.run_id=a.run_id
          WHERE a.action='release' AND a.action_sim<=%s GROUP BY a.incident_id
        ), warnings AS MATERIALIZED (
          SELECT DISTINCT ON(i.id) i.id AS incident_id,e.id AS warning_event_id,e.sim_time AS warning_sim,
            e.payload->>'due_sim' AS warning_due_sim
          FROM selected x JOIN incidents i ON i.id=x.id JOIN sim_events e ON e.run_id=i.run_id
            AND e.payload->>'incident_id'=i.id::text AND e.event_type='sla.warning' AND e.sim_time<=%s
          ORDER BY i.id,e.sim_time DESC,e.id DESC
        ) SELECT i.id,i.status,i.sla_due_sim,h.changed_sim AS stage_sim,h.to_status AS stage_status,
          r.reopened_sim,a.release_sim,w.warning_event_id,w.warning_sim,w.warning_due_sim
        FROM selected x JOIN incidents i ON i.id=x.id LEFT JOIN stages h ON h.incident_id=i.id
        LEFT JOIN resets r ON r.incident_id=i.id LEFT JOIN releases a ON a.incident_id=i.id
        LEFT JOIN warnings w ON w.incident_id=i.id
        """,
        [scope.now, list(OPEN_STATUSES), *run_args, list(OPEN_STATUSES), list(OPEN_STATUSES), scope.now, scope.now],
    )  # noqa: S608 — только внутренний predicate, значения параметризованы.
    observations = [registered_sla_risk(row, scope.now) for row in rows]
    known = sum(value is not None for value in observations)
    positive = sum(value is True for value in observations)
    value = 100 * positive / known if known else 0.0 if not rows else None
    return {
        "component": Observation(value, known, len(rows)),
        "registered_count": positive,
        "open_incidents": len(rows),
        "basis": "registered_sla_risk",
        "forecast_complete": False,
    }


async def weights_config(conn: Conn) -> dict[str, Any]:
    """TZ defaults только при отсутствии настройки; bad config явно unknown."""
    from app.analytics.cx_index import DEFAULT_WEIGHTS, validated_weights

    row = await fetch_one(conn, "SELECT value FROM settings WHERE key='cx_index'")
    value = row["value"] if row else {}
    if isinstance(value, dict) and "weights" not in value:
        return {"source": "tz_default", "weights": dict(DEFAULT_WEIGHTS), "error": None}
    try:
        weights = validated_weights(value["weights"] if isinstance(value, dict) else None)
    except ValueError:
        # Никаких raw values/неизвестных keys из произвольного settings payload.
        return {"source": "invalid", "weights": None, "error": "invalid_cx_index_weights"}
    return {"source": "configured", "weights": weights, "error": None}


async def historical_sla_facts(conn: Conn, scope: MetricsScope) -> dict[str, Any]:
    """Без deadline snapshots исторический open S не восстанавливается догадкой."""
    from app.contracts.enums import IncidentStatus
    from app.economics.dcltv import OPEN_STATUSES

    run_sql = " AND f.run_id=%s" if scope.run_id is not None else ""
    run_args = [scope.run_id] if scope.run_id is not None else []
    row = await fetch_one(
        conn,
        f"""
        WITH selected AS MATERIALIZED (
          SELECT DISTINCT f.id FROM v_cabinet_incident_facts f WHERE f.created_sim<=%s {run_sql}
        ), statuses AS MATERIALIZED (
          SELECT DISTINCT ON(h.incident_id) h.incident_id,h.to_status
          FROM incident_status_history h JOIN selected x ON x.id=h.incident_id WHERE h.changed_sim<=%s
          ORDER BY h.incident_id,h.changed_sim DESC,h.id DESC
        ) SELECT count(*) AS total,count(*) FILTER(WHERE h.to_status=ANY(%s)) AS status_known,
          count(*) FILTER(WHERE h.to_status=ANY(%s)) AS open
        FROM selected x LEFT JOIN statuses h ON h.incident_id=x.id
        """,
        [scope.now, *run_args, scope.now, [item.value for item in IncidentStatus], list(OPEN_STATUSES)],
    )  # noqa: S608 — внутренний predicate; параметры не интерполируются.
    assert row is not None
    total, known, opened = int(row["total"]), int(row["status_known"]), int(row["open"])
    population_complete = total == known
    proven_empty = population_complete and opened == 0
    return {
        "component": Observation(0.0, 0, 0)
        if proven_empty
        else Observation(None, 0, opened if population_complete else total),
        "open_incidents": opened if population_complete else None,
        "population_complete": population_complete,
        "incidents_examined": total,
        "status_known": known,
        "basis": "registered_sla_risk",
        "reason": None if proven_empty else "historical_sla_evidence_unavailable",
    }


def component_payload(
    observation: Observation, *, basis: str, numerator: int | None, total_known: bool = True
) -> dict[str, Any]:
    if observation.complete_value is not None:
        status = "complete"
    elif observation.total == 0:
        status = "empty"
    else:
        status = "partial" if observation.known else "unknown"
    return {
        "value": observation.complete_value,
        "observed_value": observation.value,
        "known": observation.known,
        "total": observation.total if total_known else None,
        "numerator": numerator,
        "status": status,
        "unit": "percent",
        "basis": basis,
    }


async def cx_index_snapshot(conn: Conn, scope: MetricsScope) -> dict[str, Any]:
    """Один readonly snapshot; обе даты используют одни текущие выбранные веса."""
    from dataclasses import replace

    from app.analytics.cx_index import DEFAULT_WEIGHTS, hourly_delta, weighted_index

    config = await weights_config(conn)
    current = await signal_facts(conn, scope)
    sla = await sla_facts(conn, scope)
    past = replace(scope, now=scope.now - dt.timedelta(hours=1))
    previous = await signal_facts(conn, past, historical=True)
    old_sla = await historical_sla_facts(conn, past)
    current["components"]["sla"] = sla["component"]
    previous["components"]["sla"] = old_sla["component"]
    weights = config["weights"]
    value = weighted_index(components=current["components"], weights=weights) if weights is not None else None
    old_value = weighted_index(components=previous["components"], weights=weights) if weights is not None else None

    def components(facts: dict[str, Any], risk: dict[str, Any], historical: bool) -> dict[str, Any]:
        result = {}
        for key, numerator in (
            ("negativity", "negativity_sum"),
            ("criticality", "criticality_high"),
            ("churn", "churn_positive"),
        ):
            result[key] = component_payload(
                facts["components"][key], basis=facts["evidence"]["basis"], numerator=facts["evidence"][numerator]
            )
        result["sla"] = component_payload(
            risk["component"],
            basis="registered_sla_risk",
            numerator=None if historical else risk["registered_count"],
            total_known=risk.get("population_complete", True),
        )
        return result

    return {
        "demonstration": True,
        "index": value,
        "previous_index": old_value,
        "delta_hour": hourly_delta(current=value, previous=old_value),
        "as_of_sim": scope.now,
        "window": {"starts_sim": scope.since, "ends_sim": scope.now},
        "previous_window": {"starts_sim": past.since, "ends_sim": past.now},
        "scope": {
            "requested_run_id": scope.requested,
            "resolved_run_id": scope.run_id if scope.run_id is not None and scope.run_id > 0 else None,
            "all_runs": scope.run_id is None,
            "current_missing": scope.current_missing,
        },
        "weights": config["weights"],
        "weights_source": config["source"],
        "weights_error": config["error"],
        "default_weights": dict(DEFAULT_WEIGHTS),
        "comparison_basis": "current_weights_on_observed_states",
        "components": components(current, sla, False),
        "previous_components": components(previous, old_sla, True),
        "sla_basis": "registered_sla_risk",
        "sla_forecast_complete": False,
        "historical_sla_reason": old_sla["reason"],
        "signals": current["signals"],
        "previous_signals": previous["signals"],
        "channel_mix": current["channel_mix"],
        "flow": current["flow"],
    }
