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
