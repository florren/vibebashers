"""Роутер тега `metrics` (T-093/T-132): KPI рабочего места (ТЗ 14.1), экономика dCLTV (14.4), факт по симуляции (14.5), центр уведомлений."""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.economics import dcltv

router = APIRouter(tags=["metrics"])

OPEN = list(dcltv.OPEN_STATUSES)


def _pct(num: float, den: float) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


@router.get("/api/metrics/dashboard", summary="KPI рабочего места (ТЗ 14.1) — по умолчанию в рамках текущего запуска")
async def get_metrics_dashboard(
    window: str = Query("run", description="run | 24h | 7d | all"), run_id: str | None = Query(None)
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, "all" if window == "all" else run_id)
        now_row = await fetch_one(conn, "select sim_time from sim_state where id = 1")
        now = now_row["sim_time"] if now_row else dt.datetime.now(dt.UTC)
        since = {"24h": now - dt.timedelta(hours=24), "7d": now - dt.timedelta(days=7)}.get(window)
        where_s: list[str] = ["true"]
        args_s: list[Any] = []
        if rid is not None:
            where_s.append("s.run_id = %s")
            args_s.append(rid)
        if since is not None:
            where_s.append("s.received_sim >= %s")
            args_s.append(since)
        ws = " and ".join(where_s)
        sig = await fetch_one(
            conn,
            f"""
            select count(*) as signals,
                   count(*) filter (where s.classification->>'criticality' = 'high') as critical,
                   count(*) filter (where s.received_sim >= %s) as signals_today,
                   count(*) filter (where s.received_sim >= %s and s.classification->>'criticality' = 'high') as critical_today,
                   count(*) filter (where (s.classification->'flags') ? 'repeat') as repeats
            from signals s where {ws}
            """,
            (now - dt.timedelta(hours=24), now - dt.timedelta(hours=24), *args_s),
        )
        sig = sig or {}
        runs = await fetch_one(
            conn,
            f"""
            select count(*) as total,
                   count(*) filter (where ar.outcome in ('completed','noise','duplicate') and not ar.needed_human) as autonomous,
                   count(*) filter (where ar.needed_human) as hitl,
                   count(*) filter (where hd.decision in ('modify','reject')) as human_changed,
                   percentile_cont(0.5) within group (order by extract(epoch from (i.created_sim - s.received_sim)) / 60) filter (where i.id is not null) as p50_min,
                   percentile_cont(0.95) within group (order by extract(epoch from (i.created_sim - s.received_sim)) / 60) filter (where i.id is not null) as p95_min,
                   percentile_cont(0.5) within group (order by ar.total_latency_ms) as run_latency_p50_ms,
                   coalesce(sum(ar.total_tokens), 0) as tokens
            from agent_runs ar join signals s on s.id = ar.signal_id
            left join incidents i on i.id = ar.incident_id and i.agent_run_id = ar.id
            left join lateral (select decision from human_decisions h where h.agent_run_id = ar.id order by h.id desc limit 1) hd on true
            where {ws}
            """,
            tuple(args_s),
        )
        runs = runs or {}
        where_i = ws.replace("s.run_id", "i.run_id").replace("s.received_sim", "i.created_sim")
        inc = await fetch_one(
            conn,
            f"""
            select count(*) as total,
                   count(*) filter (where i.status = any(%s)) as open,
                   count(*) filter (where i.status = any(%s) and i.sla_due_sim < %s + interval '2 hours' and i.sla_due_sim >= %s) as sla_risk,
                   count(*) filter (where i.status = any(%s) and i.sla_due_sim < %s) as sla_overdue,
                   count(*) filter (where i.status in ('resolved','closed')) as closed,
                   count(*) filter (where i.status in ('resolved','closed') and not i.sla_breached and coalesce(i.resolved_sim, i.closed_sim) <= i.sla_due_sim) as closed_in_sla,
                   count(*) filter (where i.report_due_sims <> '{{}}' and i.status in ('resolved','closed')) as reports_due,
                   count(*) filter (where i.outcome_class = 'closed_with_regression') as regression
            from incidents i where {where_i}
            """,
            (OPEN, OPEN, now, now, OPEN, now, *args_s),
        )
        inc = inc or {}
        seg = await fetch_all(
            conn,
            f"""
            select c.segment_code, percentile_cont(0.5) within group (order by extract(epoch from (n.sent_sim - s.received_sim)) / 60) as p50_min
            from notifications n join signals s on s.id = n.signal_id join clients c on c.id = n.client_id
            where n.recipient_type = 'client' and n.sent_sim >= s.received_sim and {ws} group by 1
            """,
            tuple(args_s),
        )
        churn = await fetch_one(
            conn,
            f"""
            select count(distinct c.id) filter (where c.churn_risk >= 60) as at_risk,
                   count(*) filter (where cs.state = 'churned' and cs.is_current) as churned,
                   count(*) filter (where cs.state = 'retained' and cs.is_current) as retained
            from clients c left join client_states cs on cs.client_id = c.id and cs.is_current
            {"where cs.run_id = %s or cs.run_id is null" if rid is not None else ""}
            """,
            (rid,) if rid is not None else (),
        )
        churn = churn or {}
        closures = await fetch_one(
            conn,
            f"select count(*) as n from churn_events ce {'where ce.run_id = %s' if rid is not None else ''}",
            (rid,) if rid is not None else (),
        )
        ret_outcome = await fetch_all(
            conn,
            f"select outcome_class, retention_rate from v_retention_by_outcome {'where run_id = %s' if rid is not None else ''}",
            (rid,) if rid is not None else (),
        )
        ret_psy = await fetch_all(
            conn,
            f"""
            select c.psychotype_code, round(count(*) filter (where cs.state = 'retained')::numeric / nullif(count(*), 0), 3) as rate
            from client_states cs join clients c on c.id = cs.client_id
            where cs.state in ('retained','churned') {"and cs.run_id = %s" if rid is not None else ""} group by 1
            """,
            (rid,) if rid is not None else (),
        )
        twin = await fetch_one(
            conn,
            f"select avg(care_score)::float as avg from client_states cs where cs.is_current and cs.care_score is not null {'and cs.run_id = %s' if rid is not None else ''}",
            (rid,) if rid is not None else (),
        )
        econ = await dcltv.summary(conn, run_id=rid, group_by="product", window=window)
    total_runs = int((runs or {}).get("total") or 0)
    out = {
        "window": window,
        "run_id": rid,
        "signals_today": int(sig["signals_today"]),
        "critical_today": int(sig["critical_today"]),
        "signals_total": int(sig["signals"]),
        "critical_total": int(sig["critical"]),
        "signal_to_incident_p50_min": round(float(runs["p50_min"] or 0), 1),
        "signal_to_incident_p95_min": round(float(runs["p95_min"] or 0), 1),
        "agent_latency_p50_ms": round(float(runs["run_latency_p50_ms"] or 0)),
        "autonomous_share": _pct(float(runs["autonomous"] or 0), total_runs),
        "hitl_share": _pct(float(runs["hitl"] or 0), total_runs),
        "human_changed_share": _pct(float(runs["human_changed"] or 0), float(runs["hitl"] or 0)),
        "agent_runs": total_runs,
        "tokens_total": int(runs["tokens"] or 0),
        "incidents_total": int(inc["total"]),
        "incidents_open": int(inc["open"]),
        "sla_risk_count": int(inc["sla_risk"]),
        "sla_overdue_count": int(inc["sla_overdue"]),
        "sla_compliance_pct": _pct(float(inc["closed_in_sla"] or 0), float(inc["closed"] or 0)),
        "reports_on_time_pct": 100.0
        if int(inc["reports_due"] or 0) == 0
        else _pct(float(inc["closed_in_sla"] or 0), float(inc["reports_due"])),
        "first_response_by_segment": {r["segment_code"]: round(float(r["p50_min"] or 0), 1) for r in seg},
        "repeat_signals_share": _pct(float(sig["repeats"] or 0), float(sig["signals"] or 0)),
        "closed_loops": int(inc["closed"]),
        "churn_risk_clients": int(churn["at_risk"] or 0),
        "churned_clients": int(churn["churned"] or 0),
        "retained_clients": int(churn["retained"] or 0),
        "retention_by_outcome": {
            r["outcome_class"]: float(r["retention_rate"]) for r in ret_outcome if r["retention_rate"] is not None
        },
        "retention_by_psychotype": {r["psychotype_code"]: float(r["rate"]) for r in ret_psy if r["rate"] is not None},
        "account_closures": int((closures or {}).get("n") or 0),
        "regression_share": _pct(float(inc["regression"] or 0), float(inc["closed"] or 0)),
        "twin_satisfaction_avg": round(float(twin["avg"]), 1) if twin and twin.get("avg") is not None else None,
        "economics": econ,
    }
    return JSONResponse(jsonable_encoder(out))


@router.get(
    "/api/metrics/economics",
    summary="Экономика dCLTV — потенциальные, предотвращённые, под риском, реализованные (ТЗ 14.4)",
)
async def get_metrics_economics(
    window: str = Query("14d"),
    group_by: str = Query("product", description="product | region | segment | team | type"),
    run_id: str | None = Query(None),
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        res = await dcltv.summary(conn, run_id=rid, group_by=group_by, window=window)
    return JSONResponse(jsonable_encoder(res))


async def _fact(
    conn: Any, rid: int | None, product: str | None, system: str | None, region: str | None
) -> dict[str, Any]:
    args: list[Any] = []
    w = ["true"]
    if rid is not None:
        w.append("f.run_id = %s")
        args.append(rid)
    if product:
        w.append("f.product_code = %s")
        args.append(product)
    if system:
        w.append("f.system_code = %s")
        args.append(system)
    matrix = await fetch_all(
        conn,
        f"select f.product_code, f.system_code, f.sim_day::date as sim_day, f.sim_hour, f.faults::int, f.operations_affected::int, f.clients_affected::int, "
        f"(select count(*) from signals s where s.source_fault_id in (select id from faults x where x.system_code = f.system_code and date_trunc('day', x.started_sim) = f.sim_day))::int as signals "
        f"from v_faults_by_product_hour f where {' and '.join(w)} order by sim_day desc, sim_hour desc limit 500",
        tuple(args),
    )
    oargs: list[Any] = []
    ow = ["true"]
    if rid is not None:
        ow.append("i.run_id = %s")
        oargs.append(rid)
    if product:
        ow.append("i.product_code = %s")
        oargs.append(product)
    if region:
        ow.append("i.region_code = %s")
        oargs.append(region)
    outcomes = await fetch_all(
        conn,
        f"select coalesce(i.outcome_class, 'open') as outcome_class, count(*)::int as incidents, coalesce(sum(e.potential_loss_rub), 0)::float as potential_loss_rub, "
        f"coalesce(sum(e.prevented_loss_rub), 0)::float as prevented_loss_rub, coalesce(sum(e.realized_loss_rub), 0)::float as realized_loss_rub "
        f"from incidents i left join incident_economics e on e.incident_id = i.id where {' and '.join(ow)} group by 1 order by 1",
        tuple(oargs),
    )
    churned = await fetch_all(
        conn,
        f"""
        select jsonb_build_object('id', c.id, 'public_id', c.public_id, 'display_name', c.display_name, 'segment_code', c.segment_code, 'region_code', c.region_code) as client,
               c.psychotype_code, ce.churn_sim, ce.days_after_incident::float, ce.reason, ce.offered, ce.realized_loss_rub::float, ce.closure_incident_id
        from churn_events ce join clients c on c.id = ce.client_id {"where ce.run_id = %s" if rid is not None else ""} order by ce.churn_sim desc limit 200
        """,
        (rid,) if rid is not None else (),
    )
    cfg = await dcltv.load_settings(conn)
    s = cfg["settings"]
    facts = await fetch_all(
        conn,
        f"select outcome_class, retention_rate, resolved_clients from v_retention_by_outcome {'where run_id = %s' if rid is not None else ''}",
        (rid,) if rid is not None else (),
    )
    by_out = {f["outcome_class"]: f for f in facts}
    det = await fetch_one(
        conn,
        f"""
        select count(*) filter (where cs.state in ('retained','churned')) as resolved, count(*) filter (where cs.state = 'churned') as churned,
               count(*) filter (where cs.state = 'detractor') as detractors, count(*) as total
        from client_states cs {"where cs.run_id = %s" if rid is not None else ""}
        """,
        (rid,) if rid is not None else (),
    )
    total = float((det or {}).get("total") or 0)
    resolved = float((det or {}).get("resolved") or 0)
    return {
        "faults_matrix": matrix,
        "outcomes": outcomes,
        "churned": churned,
        "assumptions_vs_fact": {
            "detractor_share": {
                "assumed": float(s.get("detractor_share") or 0.1),
                "fact": round(float(det.get("detractors") or 0) / total, 4) if det and total else None,
            },
            "no_return_share": {
                "assumed": float(s.get("no_return_share") or 0.5),
                "fact": round(float(det.get("churned") or 0) / resolved, 4) if det and resolved else None,
            },
            "retention_factors": {
                k: {
                    "manual": float(v),
                    "simulated": float(by_out[k]["retention_rate"])
                    if k in by_out and by_out[k]["retention_rate"] is not None
                    else None,
                    "sample": int(by_out[k]["resolved_clients"]) if k in by_out else 0,
                }
                for k, v in (s.get("retention_factors") or {}).items()
            },
        },
        "calibration_mode": s.get("calibration_mode", "manual"),
    }


@router.get(
    "/api/metrics/economics/fact", summary="Калькулятор «Факт по симуляции» (ТЗ 14.5) — по умолчанию текущий запуск"
)
async def get_metrics_economics_fact(
    product: str | None = Query(None),
    system: str | None = Query(None),
    region_code: str | None = Query(None),
    run_id: str | None = Query(None),
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        await dcltv.recompute(conn, run_id=rid)
        res = await _fact(conn, rid, product, system, region_code)
    return JSONResponse(jsonable_encoder(res))


@router.get("/api/metrics/economics/fact/export", summary="Экспорт факта (CSV/XLSX)")
async def get_metrics_economics_fact_export(
    format: Literal["csv", "xlsx"] = Query("csv"), run_id: str | None = Query(None)
) -> Any:  # noqa: A002
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        res = await _fact(conn, rid, None, None, None)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["section", "key", "incidents", "potential_loss_rub", "prevented_loss_rub", "realized_loss_rub"])
    for o in res["outcomes"]:
        w.writerow(
            [
                "outcome",
                o["outcome_class"],
                o["incidents"],
                o["potential_loss_rub"],
                o["prevented_loss_rub"],
                o["realized_loss_rub"],
            ]
        )
    w.writerow([])
    w.writerow(
        [
            "product_code",
            "system_code",
            "sim_day",
            "sim_hour",
            "faults",
            "operations_affected",
            "clients_affected",
            "signals",
        ]
    )
    for m in res["faults_matrix"]:
        w.writerow(
            [
                m["product_code"],
                m["system_code"],
                m["sim_day"],
                m["sim_hour"],
                m["faults"],
                m["operations_affected"],
                m["clients_affected"],
                m["signals"],
            ]
        )
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    media = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # xlsx без внешних зависимостей не собираем — отдаём CSV с корректным именем файла (Excel открывает напрямую)
    name = f"economics_fact_run{rid or 'all'}.csv"
    return Response(
        content=data,
        media_type=media if format == "csv" else "text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class CalibrateBody(BaseModel):
    mode: Literal["manual", "simulated"]


@router.post(
    "/api/metrics/economics/calibrate", summary="«Подставить факт в калькулятор» — переключить calibration_mode"
)
async def post_metrics_economics_calibrate(body: CalibrateBody) -> Any:
    async with db() as conn:
        await conn.execute(
            "update economics_settings set calibration_mode = %s, updated_at = now() where id = 1", (body.mode,)
        )
        rid = await resolve_run_id(conn, None)
        n = await dcltv.recompute(conn, run_id=rid, only_stale=False)
        res = await dcltv.summary(conn, run_id=rid)
    return JSONResponse(jsonable_encoder({"calibration_mode": body.mode, "recomputed": n, "economics": res}))


@router.get("/api/notifications", summary="Центр уведомлений (все исходящие сообщения)")
async def get_notifications(
    recipient_type: str | None = Query(None),
    client_id: int | None = Query(None),
    incident_id: int | None = Query(None),
    run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("n.run_id = %s")
            args.append(rid)
        if recipient_type:
            where.append("n.recipient_type = %s")
            args.append(recipient_type)
        if client_id is not None:
            where.append("n.client_id = %s")
            args.append(client_id)
        if incident_id is not None:
            where.append("n.incident_id = %s")
            args.append(incident_id)
        if cursor:
            where.append("n.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"""
            select n.id, n.recipient_type, n.channel_code, n.template_code, n.subject, n.body, n.status, n.sent_sim, n.client_id, n.incident_id,
                   n.team_code, n.signal_id, c.display_name as client_name, c.segment_code, i.public_id as incident_public_id
            from notifications n left join clients c on c.id = n.client_id left join incidents i on i.id = n.incident_id
            where {" and ".join(where)} order by n.id desc limit %s
            """,
            (*args, limit + 1),
        )
    items = rows[:limit]
    return JSONResponse(
        jsonable_encoder({"items": items, "next_cursor": str(items[-1]["id"]) if len(rows) > limit and items else None})
    )


@router.get(
    "/api/metrics/economics/live",
    summary="[ДТЗ FR-5.4] Живой тикер финансового эффекта: CLV под риском, предотвращённые и потенциальные потери текущего запуска (тот же payload — WS metrics/economics_live)",
)
async def get_metrics_economics_live(run_id: str | None = Query(None)) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        res = await dcltv.summary(conn, run_id=rid)
        open_cnt = await fetch_one(
            conn,
            f"select count(*) as n from incidents i where i.status = any(%s) {'and i.run_id = %s' if rid is not None else ''}",
            (OPEN, *((rid,) if rid is not None else ())),
        )
    return JSONResponse(
        jsonable_encoder(
            {
                "run_id": int(rid or 0),
                "clv_at_risk_rub": res["at_risk_open_rub"],
                "prevented_rub": res["prevented_loss_rub"],
                "potential_loss_rub": res["potential_loss_rub"],
                "open_incidents": int((open_cnt or {}).get("n") or 0),
                "computed_at": dt.datetime.now(dt.UTC),
            }
        )
    )
