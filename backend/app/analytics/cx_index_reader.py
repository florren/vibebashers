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
        return MetricsScope(requested, None, state["sim_time"])
    if requested == "current":
        current = state["current_run_id"]
        return MetricsScope(requested, int(current) if current is not None else -1, state["sim_time"], current is None)
    rid = int(requested)
    if await fetch_one(conn, "SELECT id FROM sim_runs WHERE id=%s", (rid,)) is None:
        raise HTTPException(404, "Запуск не найден")
    return MetricsScope(requested, rid, state["sim_time"])


async def signal_facts(conn: Conn, scope: MetricsScope) -> dict[str, Any]:
    """N/C/R и24rolling-hour buckets; raw default flags не являются классификацией."""
    run_sql = " AND f.run_id=%s" if scope.run_id is not None else ""
    run_args = [scope.run_id] if scope.run_id is not None else []
    facts = await fetch_one(
        conn,
        f"""
        WITH selected AS MATERIALIZED (
          SELECT f.id,f.received_sim,f.channel_code,s.classification AS c
          FROM v_cabinet_signal_facts f JOIN signals s ON s.id=f.id
          WHERE f.received_sim>%s AND f.received_sim<=%s {run_sql}
        ), numeric_facts AS MATERIALIZED (
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
        ) SELECT count(*) AS total,count(negativity) AS negativity_known,avg(negativity) AS negativity_value,
          count(criticality) AS criticality_known,count(*) FILTER(WHERE criticality='high') AS criticality_high,
          count(churn) AS churn_known,count(*) FILTER(WHERE churn) AS churn_positive,
          (SELECT jsonb_agg(to_jsonb(m) ORDER BY m.channel_code) FROM channel_mix m) AS channel_mix,
          (SELECT jsonb_agg(to_jsonb(f) ORDER BY f.bucket) FROM flow f) AS flow
        FROM scored
        """,
        [
            scope.since,
            scope.now,
            *run_args,
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
