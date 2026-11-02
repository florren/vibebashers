"""T-241: пакетные SQL-агрегаты кабинета, только сохранённые наблюдения."""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from app.analytics.cabinet_scope import CabinetScope
from app.analytics.map_thresholds import map_thresholds
from app.api.common import fetch_one
from app.corpus.reviews import project_platform
from app.trace.store import Conn


async def overview(conn: Conn, scope: CabinetScope) -> dict[str, Any]:
    signal_where, signal_args = scope.predicate("s")
    incident_where, incident_args = scope.predicate("i", time_column="created_sim")
    local_now = scope.now.astimezone(ZoneInfo("Europe/Moscow"))
    daily_since = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=29)
    daily_signal, daily_signal_args = scope.predicate("s", since=daily_since)
    daily_incident, daily_incident_args = scope.predicate("i", since=daily_since, time_column="created_sim")
    history_args: list[Any] = [scope.now, scope.now]
    history_parts = [
        "h.month >= (date_trunc('month',%s::timestamptz AT TIME ZONE 'Europe/Moscow')-interval '11 months')::date",
        "h.month <= date_trunc('month',%s::timestamptz AT TIME ZONE 'Europe/Moscow')::date",
    ]
    if scope.run_ids is not None:
        history_parts.append("h.run_id=ANY(%s)")
        history_args.append(scope.run_ids)
    if scope.lines is not None:
        history_parts.append("h.product_line_code=ANY(%s)")
        history_args.append(scope.lines)
    month_index = local_now.year * 12 + local_now.month - 1 - 11
    year_since = local_now.replace(
        year=month_index // 12, month=month_index % 12 + 1, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    live_where, live_args = scope.predicate("s", since=year_since)
    live_incident_where, live_incident_args = scope.predicate("i", since=year_since, time_column="created_sim")
    row = await fetch_one(
        conn,
        f"""
      WITH selected_signals AS MATERIALIZED (SELECT s.* FROM v_cabinet_signal_facts s WHERE {signal_where}),
      selected_incidents AS MATERIALIZED (SELECT DISTINCT i.id,i.run_id,i.created_sim,i.region_code,i.status,i.criticality,i.sla_due_sim,i.potential_loss_rub,i.prevented_loss_rub,i.computed_at FROM v_cabinet_incident_facts i WHERE {incident_where}),
      signal_kpi AS (SELECT count(*) AS signals,count(*) FILTER(WHERE sentiment IN ('positive','neutral','negative')) AS sentiment_known,
        count(*) FILTER(WHERE sentiment='negative') AS negative,count(*) FILTER(WHERE criticality IN ('high','medium','low')) AS criticality_known,
        count(*) FILTER(WHERE criticality='high') AS critical,count(*) FILTER(WHERE product_line_code IS NOT NULL) AS mapped,
        count(*) FILTER(WHERE region_code IS NULL) AS no_geo FROM selected_signals),
      economy AS (SELECT count(*) AS incidents,count(computed_at) AS economics_known,
        CASE WHEN count(computed_at)=count(*) THEN sum(potential_loss_rub) END AS potential_loss_rub,CASE WHEN count(computed_at)=count(*) THEN sum(prevented_loss_rub) END AS prevented_loss_rub,
        min(computed_at) AS oldest_computed_at FROM selected_incidents),
      sources AS (SELECT source_platform AS code,count(*) AS signals FROM selected_signals GROUP BY 1),
      region_incidents AS (SELECT region_code,count(*) FILTER(WHERE criticality='high' AND status NOT IN ('closed','resolved','rejected','duplicate')) AS critical_incidents FROM selected_incidents GROUP BY 1),
      selected_sessions AS (SELECT DISTINCT a.id,a.run_id,b.region_code FROM selected_incidents i
        JOIN compliance_alerts al ON al.incident_id=i.id JOIN audio_sessions a ON a.id=al.session_id AND a.run_id=i.run_id
        JOIN employees e ON e.id=a.employee_id JOIN branches b ON b.id=e.branch_id),
      region_copilot AS (SELECT a.region_code,count(DISTINCT a.id) AS sessions,
        count(DISTINCT tr.id) FILTER(WHERE tr.status='confirmed') AS triggers,
        count(DISTINCT al.id) FILTER(WHERE al.kind IN ('threshold','immediate')) AS alerts
        FROM selected_sessions a LEFT JOIN compliance_triggers tr ON tr.session_id=a.id
        LEFT JOIN compliance_alerts al ON al.session_id=a.id AND al.incident_id IN (SELECT id FROM selected_incidents)
        GROUP BY 1),
      regions AS (SELECT r.code,r.name_ru,r.name_en,r.centroid_lat AS lat,r.centroid_lon AS lon,count(s.id) AS signals,
        count(s.id) FILTER(WHERE s.sentiment='negative') AS negative,
        count(s.id) FILTER(WHERE s.criticality='high') AS critical,
        count(DISTINCT s.client_id) AS affected_clients,
        coalesce(max(ri.critical_incidents),0)+coalesce(max(rc.alerts),0) AS critical_count,
        CASE WHEN max(rc.sessions)>0 THEN least(1,(max(rc.triggers)::float/3+max(rc.alerts))/max(rc.sessions)) END AS copilot_index
        FROM regions r LEFT JOIN selected_signals s ON s.region_code=r.code
        LEFT JOIN region_incidents ri ON ri.region_code=r.code LEFT JOIN region_copilot rc ON rc.region_code=r.code GROUP BY r.code),
      daily_signals AS (SELECT (s.received_sim AT TIME ZONE 'Europe/Moscow')::date AS day,count(*) AS signals
        FROM v_cabinet_signal_facts s WHERE {daily_signal} GROUP BY 1),
      daily_incidents AS (SELECT DISTINCT i.id,i.created_sim,i.potential_loss_rub,i.prevented_loss_rub,i.computed_at
        FROM v_cabinet_incident_facts i WHERE {daily_incident}),
      daily_economy AS (SELECT (created_sim AT TIME ZONE 'Europe/Moscow')::date AS day,count(*) AS incidents,
        count(computed_at) AS economics_known,CASE WHEN count(computed_at)=count(*) THEN sum(potential_loss_rub) END AS potential_loss_rub,
        CASE WHEN count(computed_at)=count(*) THEN sum(prevented_loss_rub) END AS prevented_loss_rub FROM daily_incidents GROUP BY 1),
      days AS (SELECT generate_series(%s::date,%s::date,interval '1 day')::date AS day),
      daily AS (SELECT d.day,s.signals,e.incidents,e.economics_known,e.potential_loss_rub,e.prevented_loss_rub
        FROM days d LEFT JOIN daily_signals s USING(day) LEFT JOIN daily_economy e USING(day)),
      history_parts AS (SELECT h.month,h.signal_count AS signals,h.sentiment_known_count AS sentiment_known,
        h.negative_count AS negative,h.critical_count AS critical,h.loss_rub AS potential_loss_rub,
        h.is_synthetic,h.is_partial,(h.run_id IS NULL OR h.sentiment_known_count IS NULL OR h.is_partial IS NULL) AS quality_unknown,
        h.coverage_start,h.coverage_end
        FROM product_signal_history h WHERE {" AND ".join(history_parts)} AND (h.is_synthetic OR h.run_id IS NULL)),
      live_months AS (SELECT date_trunc('month',s.received_sim AT TIME ZONE 'Europe/Moscow')::date AS month,
        count(*) AS signals,count(*) FILTER(WHERE sentiment IN ('positive','neutral','negative')) AS sentiment_known,
        count(*) FILTER(WHERE sentiment='negative') AS negative,count(*) FILTER(WHERE criticality='high') AS critical,
        min(s.received_sim) AS coverage_start,max(s.received_sim) AS coverage_end
        FROM v_cabinet_signal_facts s WHERE {live_where} GROUP BY 1),
      live_economy AS (SELECT date_trunc('month',created_sim AT TIME ZONE 'Europe/Moscow')::date AS month,
        CASE WHEN count(computed_at)=count(*) THEN sum(potential_loss_rub) END AS potential_loss_rub
        FROM (SELECT DISTINCT i.id,i.created_sim,i.computed_at,i.potential_loss_rub
          FROM v_cabinet_incident_facts i WHERE {live_incident_where}) i GROUP BY 1),
      history_segments AS (SELECT * FROM history_parts UNION ALL
        SELECT l.month,l.signals,l.sentiment_known,l.negative,l.critical,e.potential_loss_rub,
        false AS is_synthetic,true AS is_partial,false AS quality_unknown,l.coverage_start,l.coverage_end
        FROM live_months l LEFT JOIN live_economy e USING(month)),
      history AS (SELECT month,sum(signals) AS signals,
        CASE WHEN count(sentiment_known)=count(*) THEN sum(sentiment_known) END AS sentiment_known,
        sum(negative) AS negative,sum(critical) AS critical,
        CASE WHEN count(potential_loss_rub)=count(*) THEN sum(potential_loss_rub) END AS potential_loss_rub,
        bool_or(is_synthetic) AS is_synthetic,bool_or(is_partial) AS is_partial,
        bool_or(quality_unknown) AS quality_unknown,min(coverage_start) AS coverage_start,max(coverage_end) AS coverage_end
        FROM history_segments GROUP BY month),
      csi AS (SELECT count(*) AS responses,count(DISTINCT cr.branch_id) AS branches,
        avg(cr.wait_min) AS average_wait_min FROM selected_signals s JOIN csi_responses cr ON cr.signal_id=s.id)
      SELECT (SELECT to_jsonb(signal_kpi) FROM signal_kpi) AS signal_kpi,
        (SELECT to_jsonb(economy) FROM economy) AS economy,
        (SELECT jsonb_agg(to_jsonb(sources) ORDER BY signals DESC,code) FROM sources) AS sources,
        (SELECT jsonb_agg(to_jsonb(regions) ORDER BY signals DESC,code) FROM regions) AS regions,
        (SELECT jsonb_agg(to_jsonb(daily) ORDER BY day) FROM daily) AS daily,
        (SELECT jsonb_agg(to_jsonb(history) ORDER BY month) FROM history) AS monthly,
        (SELECT to_jsonb(csi) FROM csi) AS csi,
        (SELECT map_zone_thresholds FROM economics_settings WHERE id=1) AS thresholds
    """,
        [
            *signal_args,
            *incident_args,
            *daily_signal_args,
            *daily_incident_args,
            daily_since.date(),
            local_now.date(),
            *history_args,
            *live_args,
            *live_incident_args,
        ],
    )  # noqa: S608 — только внутренние predicates, значения параметризованы.
    assert row is not None
    kpi = {**row["signal_kpi"], **row["economy"]}
    kpi["negative_share"] = kpi["negative"] / kpi["sentiment_known"] if kpi["sentiment_known"] else None
    kpi["critical_share"] = kpi["critical"] / kpi["criticality_known"] if kpi["criticality_known"] else None
    regions = row["regions"] or []
    thresholds = map_thresholds(row["thresholds"] or {})
    max_negative = max((r["negative"] for r in regions), default=0) or 1
    for region in regions:
        negativity = region["negative"] / max_negative
        region["negativity_index"] = negativity
        index = min(1.0, negativity + float(thresholds["copilot_weight"]) * (region["copilot_index"] or 0))
        region["zone_index"] = index
        region["zone"] = (
            "red"
            if region["critical_count"] >= int(thresholds["critical_red"]) or index >= float(thresholds["red"])
            else "yellow"
            if index >= float(thresholds["yellow"])
            else "green"
        )
        if region["signals"] == 0 and region["critical_count"] == 0:
            region["zone"] = "green"
    sources = [{"platform": project_platform(x["code"]), "signals": x["signals"]} for x in row["sources"] or []]
    return {
        "scope": {
            "role": scope.role,
            "visibility": scope.visibility,
            "product_lines": scope.lines,
            "run_ids": scope.run_ids,
            "period": scope.period,
            "since_sim": scope.since,
            "sim_time": scope.now,
        },
        "product_lines": scope.available_lines,
        "kpi": kpi,
        "regions": regions,
        "top_regions": [x for x in regions if x["signals"]][:5],
        "sources": sources,
        "daily": row["daily"] or [],
        "monthly": row["monthly"] or [],
        "csi": row["csi"],
        "history_note": "synthetic_aggregates_and_observed_live_tail",
        "economics_note": "saved_incident_economics_only",
    }
