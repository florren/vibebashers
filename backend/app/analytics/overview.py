"""T-256/T-255: readonly KPI и компиляция сохранённых summaries, не новый LLM текст."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.analytics.cx_index_reader import MetricsScope, signal_facts, sla_facts
from app.api.common import fetch_all, fetch_one
from app.trace.privacy import mask
from app.trace.store import Conn

SUMMARY_LIMIT = 8


def summary_mode(row: dict[str, Any]) -> str:
    """Только фактическая model/source запись; unknown legacy не выдаётся за live."""
    output = row.get("output")
    output = output if isinstance(output, dict) else {}
    source = output.get("llm_source") or output.get("source")
    if source in ("mock", "replay", "live"):
        return str(source)
    model = str(row.get("model") or "")
    if model.startswith("mock"):
        return "mock"
    if model.startswith(("replay:", "replay/")):
        return "replay"
    return "live" if model.startswith(("gigachat:", "openai_compatible:")) else "unknown"


async def overview_snapshot(conn: Conn, scope: MetricsScope) -> dict[str, Any]:
    facts, sla = await signal_facts(conn, scope), await sla_facts(conn, scope)
    run_sql = " AND f.run_id=%s" if scope.run_id is not None else ""
    run_args = [scope.run_id] if scope.run_id is not None else []
    day_start = scope.now.astimezone(ZoneInfo("Europe/Moscow")).replace(hour=0, minute=0, second=0, microsecond=0)
    row = await fetch_one(
        conn,
        f"""
        WITH customer AS MATERIALIZED (
          SELECT f.id,f.received_sim,f.criticality FROM v_cabinet_signal_facts f
          WHERE f.received_sim>%s AND f.received_sim<=%s {run_sql}
        ), runs AS MATERIALIZED (
          SELECT a.id,a.outcome,a.needed_human,a.total_latency_ms,
            EXISTS(SELECT 1 FROM agent_steps st WHERE st.run_id=a.id AND st.finished_at IS NOT NULL) AS timed
          FROM agent_runs a JOIN customer s ON s.id=a.signal_id
          JOIN signals f ON f.id=s.id AND f.run_id=a.sim_run_id
          WHERE a.kind='agent' AND a.finished_at IS NOT NULL
        ), incidents AS MATERIALIZED (
          SELECT DISTINCT f.id,f.computed_at,f.prevented_loss_rub FROM v_cabinet_incident_facts f
          WHERE f.created_sim>%s AND f.created_sim<=%s {run_sql}
        ) SELECT
          (SELECT count(*) FROM customer WHERE received_sim>=%s) AS signals_today,
          (SELECT count(*) FROM customer WHERE received_sim>=%s AND criticality IN ('low','medium','high')) AS criticality_known_today,
          (SELECT count(*) FROM customer WHERE received_sim>=%s AND criticality='high') AS critical_today,
          (SELECT count(*) FROM runs) AS agent_runs,
          (SELECT count(*) FROM runs WHERE outcome IN ('completed','failed','fallback_mock','cancelled','awaiting_human','deferred')) AS outcome_known,
          (SELECT count(*) FROM runs WHERE outcome='completed' AND NOT needed_human) AS autonomous,
          (SELECT count(*) FROM runs WHERE timed AND total_latency_ms>=0) AS latency_known,
          (SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY total_latency_ms) FROM runs WHERE timed AND total_latency_ms>=0) AS latency_p50_ms,
          (SELECT count(*) FROM incidents) AS incidents,
          (SELECT count(*) FROM incidents WHERE computed_at IS NOT NULL AND prevented_loss_rub IS NOT NULL) AS economics_known,
          (SELECT sum(prevented_loss_rub) FROM incidents WHERE computed_at IS NOT NULL) AS saved_rub,
          (SELECT min(computed_at) FROM incidents) AS oldest_computed_at
        """,
        [scope.since, scope.now, *run_args, scope.since, scope.now, *run_args, day_start, day_start, day_start],
    )  # noqa: S608 — внутренний predicate, все значения параметризованы.
    assert row is not None
    pressure = await fetch_all(
        conn,
        f"""SELECT f.status,f.criticality,count(DISTINCT f.id) AS incidents
          FROM v_cabinet_incident_facts f WHERE f.created_sim<=%s {run_sql}
          GROUP BY f.status,f.criticality ORDER BY f.status,f.criticality""",
        [scope.now, *run_args],
    )  # noqa: S608 — внутренний predicate, все значения параметризованы.
    summaries = await fetch_all(
        conn,
        f"""WITH candidates AS MATERIALIZED (
          SELECT a.id AS agent_run_id,f.id AS signal_id,s.public_id,a.started_sim,st.node,st.model,st.output,
            CASE WHEN st.node='classify' THEN st.output->>'summary_ru'
              ELSE st.output->'classification_snapshot'->>'summary_ru' END AS summary,
            count(*) OVER() AS total
          FROM v_cabinet_signal_facts f JOIN signals s ON s.id=f.id
          JOIN agent_runs a ON a.signal_id=f.id AND a.sim_run_id=f.run_id AND a.kind='agent'
          JOIN agent_steps st ON st.run_id=a.id AND st.node IN ('classify','instant_decide') AND st.status IN ('ok','fallback')
          WHERE f.received_sim>%s AND f.received_sim<=%s {run_sql}
            AND CASE WHEN st.node='classify' THEN st.output->>'summary_ru'
              ELSE st.output->'classification_snapshot'->>'summary_ru' END IS NOT NULL
        ) SELECT * FROM candidates ORDER BY started_sim DESC NULLS LAST,agent_run_id DESC LIMIT %s""",
        [scope.since, scope.now, *run_args, SUMMARY_LIMIT],
    )  # noqa: S608 — внутренний predicate, все значения параметризованы.
    total = int(summaries[0]["total"]) if summaries else 0
    money_complete = row["incidents"] == row["economics_known"]
    money = (row["saved_rub"] if row["incidents"] else Decimal(0)) if money_complete else None
    return {
        "as_of_sim": scope.now,
        "scope": {
            "requested_run_id": scope.requested,
            "resolved_run_id": scope.run_id if scope.run_id and scope.run_id > 0 else None,
            "all_runs": scope.run_id is None,
            "current_missing": scope.current_missing,
        },
        "window": {"starts_sim": scope.since, "ends_sim": scope.now},
        "today_starts_sim": day_start,
        "kpi": {
            "signals_today": int(row["signals_today"]),
            "critical_today": int(row["critical_today"])
            if row["criticality_known_today"] == row["signals_today"]
            else None,
            "autonomous_share": 100 * row["autonomous"] / row["agent_runs"]
            if row["agent_runs"] and row["outcome_known"] == row["agent_runs"]
            else None,
            "agent_response_p50_ms": float(row["latency_p50_ms"])
            if row["agent_runs"] and row["latency_known"] == row["agent_runs"]
            else None,
            "sla_risk_incidents": sla["registered_count"] if sla["component"].known == sla["component"].total else None,
            "saved_rub_exact": format(money, "f") if money is not None else None,
        },
        "coverage": {
            "signals_today": int(row["signals_today"]),
            "criticality_known_today": int(row["criticality_known_today"]),
            "agent_runs": int(row["agent_runs"]),
            "outcome_known": int(row["outcome_known"]),
            "latency_known": int(row["latency_known"]),
            "incidents": int(row["incidents"]),
            "economics_known": int(row["economics_known"]),
            "sla_known": sla["component"].known,
            "sla_open": sla["component"].total,
        },
        "economics_basis": "saved_incident_economics_only",
        "oldest_computed_at": row["oldest_computed_at"],
        "sla_basis": "registered_sla_risk",
        "sla_forecast_complete": False,
        "response_basis": "recorded_agent_run_latency_ms",
        "pressure": pressure,
        "shift": {
            "basis": "saved_classification_compendium",
            "new_llm_call": False,
            "limit": SUMMARY_LIMIT,
            "total": total,
            "truncated": total > len(summaries),
            "items": [
                {
                    "agent_run_id": x["agent_run_id"],
                    "signal_id": x["signal_id"],
                    "public_id": x["public_id"],
                    "started_sim": x["started_sim"],
                    "node": x["node"],
                    "mode": summary_mode(x),
                    "text": mask(x["summary"], 300),
                }
                for x in summaries
            ],
        },
        "signals_24h": facts["signals"],
    }
