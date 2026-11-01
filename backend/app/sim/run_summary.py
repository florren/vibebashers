"""T-042: итоговый снимок, read-only экспорт и числовое сравнение запусков."""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, cast

import psycopg

from app.analytics.dashboard import dashboard, fact, fetch_all, fetch_one

SUMMARY_VERSION = 1


def json_values(value: Any) -> Any:
    """Числовые проекции остаются JSON numbers, временные метки сохраняют пояс."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_values(item) for item in value]
    return value


async def build_summary(
    conn: psycopg.AsyncConnection[Any], run_id: int, *, refresh_economics: bool = False
) -> dict[str, Any]:
    run = await fetch_one(
        conn, "select id,started_at,finished_at,started_sim,finished_sim from sim_runs where id=%s", (run_id,)
    )
    if run is None:
        raise LookupError("запуск не найден")
    metrics = await dashboard(conn, rid=run_id, window="run", refresh_economics=refresh_economics)
    facts = await fact(conn, run_id, None, None, None)
    profiles = await fetch_all(
        conn,
        "select ar.llm_profile_id,p.code,p.provider,p.model,p.price_in_per_1m,p.price_out_per_1m,ar.kind,count(*) runs,"
        "sum(ar.prompt_tokens) prompt_tokens,sum(ar.completion_tokens) completion_tokens,sum(ar.total_tokens) total_tokens,"
        "sum(ar.cost_estimate) recorded_cost_estimate,"
        "case when p.id is null then null else sum((ar.prompt_tokens*p.price_in_per_1m+ar.completion_tokens*p.price_out_per_1m)/1000000.0) end tariff_cost_estimate "
        "from agent_runs ar left join llm_profiles p on p.id=ar.llm_profile_id where ar.sim_run_id=%s "
        "group by ar.llm_profile_id,p.id,ar.kind order by ar.llm_profile_id nulls last,ar.kind",
        (run_id,),
    )
    counters = await fetch_one(conn, "select * from v_run_counters where run_id=%s", (run_id,))
    quality = await fetch_one(
        conn,
        "select count(*) filter(where e.incident_id is null) missing_incidents,count(*) filter(where e.computed_at<i.updated_at) stale_incidents from incidents i left join incident_economics e on e.incident_id=i.id where i.run_id=%s",
        (run_id,),
    )
    gifts = await fetch_one(
        conn,
        "select count(*) filter(where status='done') n,count(*) tasks_total from tasks where run_id=%s and kind='gift'",
        (run_id,),
    )
    now_row = await fetch_one(conn, "select sim_time from sim_state where id=1")
    real_end = run["finished_at"] or dt.datetime.now(dt.UTC)
    sim_end = run["finished_sim"] or (now_row or {}).get("sim_time") or run["started_sim"]
    return cast(
        dict[str, Any],
        json_values(
            {
                # Сохраняем прежние ключи счётчиков для существующих потребителей истории.
                **{
                    key: value
                    for key, value in (counters or {}).items()
                    if key not in ("run_id", "kind", "label", "status", "started_sim", "finished_sim")
                },
                "summary_version": SUMMARY_VERSION,
                "run_id": run_id,
                "dashboard": metrics,
                "economics": metrics["economics"],
                "economics_quality": quality,
                "fact": facts,
                "llm_profiles": profiles,
                "llm": {
                    "prompt_tokens": sum(row["prompt_tokens"] for row in profiles),
                    "completion_tokens": sum(row["completion_tokens"] for row in profiles),
                    "total_tokens": sum(row["total_tokens"] for row in profiles),
                    "recorded_cost_estimate": sum(row["recorded_cost_estimate"] for row in profiles),
                    "known_tariff_cost_estimate": sum(row["tariff_cost_estimate"] or 0 for row in profiles),
                    "unknown_tariff_runs": sum(row["runs"] for row in profiles if row["tariff_cost_estimate"] is None),
                },
                "duration_real_seconds": max(0.0, (real_end - run["started_at"]).total_seconds()),
                "duration_sim_seconds": max(0.0, (sim_end - run["started_sim"]).total_seconds()),
                "gifts": int((gifts or {}).get("n") or 0),
                "gift_tasks_total": int((gifts or {}).get("tasks_total") or 0),
                "calculated_at": dt.datetime.now(dt.UTC),
                "cost_note": "recorded_cost_estimate — сохранённая оценка; tariff_cost_estimate — пересчёт по текущим тарифам профиля, не фактический счёт провайдера",
            }
        ),
    )


async def export_json(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[str, Any]:
    run = await fetch_one(
        conn,
        "select id,kind,label,status,seed,started_sim,finished_sim,started_at,finished_at,summary from sim_runs where id=%s",
        (run_id,),
    )
    if run is None:
        raise LookupError("запуск не найден")
    summary = run.pop("summary")
    if not isinstance(summary, dict) or summary.get("summary_version") != SUMMARY_VERSION:
        summary = await build_summary(conn, run_id)
    hourly = await fetch_all(
        conn,
        "with parts(sim_hour,operations,failed_operations,signals,critical_signals,incidents,sla_breached,events) as ("
        "select date_trunc('hour',started_sim),count(*),count(*) filter(where status='failed'),0,0,0,0,0 from operations where run_id=%s group by 1 union all "
        "select date_trunc('hour',received_sim),0,0,count(*),count(*) filter(where classification->>'criticality'='high'),0,0,0 from signals where run_id=%s group by 1 union all "
        "select date_trunc('hour',created_sim),0,0,0,0,count(*),count(*) filter(where sla_breached),0 from incidents where run_id=%s group by 1 union all "
        "select date_trunc('hour',sim_time),0,0,0,0,0,0,count(*) from sim_events where run_id=%s group by 1) "
        "select sim_hour,sum(operations)::bigint operations,sum(failed_operations)::bigint failed_operations,"
        "sum(signals)::bigint signals,sum(critical_signals)::bigint critical_signals,sum(incidents)::bigint incidents,"
        "sum(sla_breached)::bigint sla_breached,sum(events)::bigint events from parts group by 1 order by 1",
        (run_id,) * 4,
    )
    products = await fetch_all(
        conn,
        "select product_code,count(*) operations,count(*) filter(where status='failed') failed,coalesce(sum(amount_rub),0) amount_rub from operations where run_id=%s group by 1 order by 1",
        (run_id,),
    )
    teams = await fetch_all(
        conn,
        "select team_code,count(*) incidents,count(*) filter(where sla_breached) sla_breached from incidents where run_id=%s group by 1 order by 1",
        (run_id,),
    )
    return {
        "export_version": 1,
        "run": run,
        "summary": summary,
        "aggregates": {"hours": hourly, "products": products, "teams": teams},
    }


async def csv_events(conn: psycopg.AsyncConnection[Any], run_id: int) -> AsyncIterator[str]:
    """Именованный курсор живёт в snapshot-транзакции вызывающего кода; порции ограничены."""
    from app.sim.events import dumps

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["id", "run_id", "event_type", "sim_time", "real_time", "scenario_id", "correlation_id", "payload"])
    yield stream.getvalue()
    async with conn.cursor(name="run_export_events") as cur:
        await cur.execute(
            "select id,run_id,event_type,sim_time,real_time,scenario_id,correlation_id,payload from sim_events where run_id=%s order by id",
            (run_id,),
        )
        while rows := await cur.fetchmany(500):
            stream.seek(0)
            stream.truncate()
            for row in rows:
                values = list(row.values()) if isinstance(row, dict) else list(row)
                # Текст внешнего события тоже может содержать CSV-формулу.
                rendered = [
                    value.isoformat()
                    if isinstance(value, dt.datetime)
                    else dumps(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                    if value is not None
                    else ""
                    for value in values
                ]
                writer.writerow(
                    ["'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in rendered]
                )
            yield stream.getvalue()


def numeric_diff(a: dict[str, Any], b: dict[str, Any], prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    for key in sorted(a.keys() | b.keys()):
        if key in ("run_id", "summary_version"):
            continue
        left, right = a.get(key), b.get(key)
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(left, dict) and isinstance(right, dict):
            result.update(numeric_diff(left, right, name))
        elif (
            isinstance(left, (int, float, Decimal))
            and isinstance(right, (int, float, Decimal))
            and not isinstance(left, bool)
            and not isinstance(right, bool)
        ):
            result[name] = float(right) - float(left)
    return result
