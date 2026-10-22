"""Роутер тега `map` (T-088/T-218): тепловая карта субъектов РФ, drill-down до городов, трёхцветные зоны (ДТЗ FR-5.2)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.common import db, fetch_all, fetch_one, resolve_run_id

router = APIRouter(tags=["map"])

LAYERS = ("signals", "critical", "incidents", "churn")


async def _sim_now(conn: Any) -> dt.datetime:
    row = await fetch_one(conn, "select sim_time from sim_state where id = 1")
    return row["sim_time"] if row else dt.datetime.now(dt.UTC)


@router.get("/api/map/heat", summary="Агрегаты по субъектам РФ для тепловой карты")
async def get_map_heat(
    layer: str = Query("signals", description="signals | critical | incidents | churn"),
    window_hours: int = Query(24, ge=1, le=24 * 30),
    run_id: str | None = Query(None, description="current (по умолчанию) | all | <id>"),
) -> Any:
    """Регион сигнала — гео сигнала (`signals.geo.region_code`), иначе регион клиента. Интенсивность нормирована к максимуму слоя (0..1)."""
    if layer not in LAYERS:
        layer = "signals"
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        now = await _sim_now(conn)
        since = now - dt.timedelta(hours=window_hours)
        run_sql = "and s.run_id = %s" if rid is not None else ""
        run_args: tuple[Any, ...] = (rid,) if rid is not None else ()
        rows = await fetch_all(
            conn,
            f"""
            with sig as (
              select coalesce(s.geo->>'region_code', c.region_code) as region_code,
                     count(*) as signals,
                     count(*) filter (where s.classification->>'criticality' = 'high') as critical,
                     avg(c.churn_risk) as churn_risk_avg
              from signals s left join clients c on c.id = s.client_id
              where s.received_sim >= %s {run_sql}
              group by 1
            ), inc as (
              select i.region_code, count(*) as incidents_open
              from incidents i
              where i.status not in ('closed','rejected','duplicate','resolved') {"and i.run_id = %s" if rid is not None else ""}
              group by 1
            )
            select r.code as region_code, r.name_ru, r.district_code, r.centroid_lat::float as lat, r.centroid_lon::float as lon,
                   coalesce(sig.signals, 0)::int as signals, coalesce(sig.critical, 0)::int as critical,
                   coalesce(inc.incidents_open, 0)::int as incidents_open, coalesce(sig.churn_risk_avg, 0)::float as churn_risk_avg
            from regions r left join sig on sig.region_code = r.code left join inc on inc.region_code = r.code
            order by r.code
            """,
            (since, *run_args, *run_args),
        )
    key = {"signals": "signals", "critical": "critical", "incidents": "incidents_open", "churn": "churn_risk_avg"}[
        layer
    ]
    vmax = max((float(r[key]) for r in rows), default=0.0) or 1.0
    out = []
    for r in rows:
        v = float(r[key])
        out.append({**r, "value": v, "intensity": round(min(1.0, v / vmax), 3) if v > 0 else 0.0})
    return JSONResponse(jsonable_encoder(out))


@router.get("/api/map/regions/{code}/cities", summary="Drill-down субъект → города")
async def get_map_regions_code_cities(
    code: str, window_hours: int = Query(24, ge=1, le=24 * 30), run_id: str | None = Query(None)
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        now = await _sim_now(conn)
        since = now - dt.timedelta(hours=window_hours)
        run_sql = "and s.run_id = %s" if rid is not None else ""
        run_args: tuple[Any, ...] = (rid,) if rid is not None else ()
        rows = await fetch_all(
            conn,
            f"""
            with sig as (
              select coalesce((s.geo->>'city_id')::bigint, cg.id, c.city_id) as city_id, s.id, s.classification->>'criticality' = 'high' as crit, s.received_sim
              from signals s left join clients c on c.id = s.client_id
              left join cities cg on cg.region_code = %s and cg.name_ru = s.geo->>'city'
              where s.received_sim >= %s and coalesce(s.geo->>'region_code', c.region_code) = %s {run_sql}
            )
            select ci.id as city_id, ci.name_ru, ci.lat::float as lat, ci.lon::float as lon, ci.population,
                   count(sig.id)::int as signals, count(sig.id) filter (where sig.crit)::int as critical,
                   coalesce((array_agg(sig.id order by sig.received_sim desc) filter (where sig.id is not null))[1:10], '{{}}') as top_signal_ids
            from cities ci left join sig on sig.city_id = ci.id
            where ci.region_code = %s
            group by ci.id order by signals desc, ci.population desc nulls last
            """,
            (code, since, code, *run_args, code),
        )
    return JSONResponse(jsonable_encoder(rows))


@router.get(
    "/api/map/zones",
    summary="[ДТЗ FR-5.2] Слой «Зоны»: зелёная/жёлтая/красная по субъектам (v_map_zones) с индексами негатива и сработок copilot",
)
async def get_map_zones(run_id: str | None = Query(None)) -> Any:
    """Зона: индекс негатива = негативные сигналы региона / максимум по регионам за окно (концентрация, 0..1) + вес copilot × индекс
    сработок комплаенс-копилота по отделениям региона. Красная — при индексе ≥ red или при ≥ critical_red критичных инцидентов/алертов
    за окно. Пороги — `economics_settings.map_zone_thresholds` (yellow, red, copilot_weight, window_sim_hours, critical_red)."""
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        th = await fetch_one(conn, "select map_zone_thresholds as t from economics_settings where id = 1")
        raw = (th or {}).get("t") or {}
        t: dict[str, Any] = {
            "yellow": 0.25,
            "red": 0.5,
            "copilot_weight": 0.5,
            "window_sim_hours": 24,
            "critical_red": 3,
            **raw,
        }
        if "yellow_max" in raw and "red" not in raw:  # старый формат порогов из сида (green_max / yellow_max)
            t["yellow"], t["red"] = float(raw.get("green_max", 0.25)), float(raw.get("yellow_max", 0.5))
        now = await _sim_now(conn)
        since = now - dt.timedelta(hours=int(t["window_sim_hours"]))
        run_sql = "and s.run_id = %s" if rid is not None else ""
        run_args: tuple[Any, ...] = (rid,) if rid is not None else ()
        rows = await fetch_all(
            conn,
            f"""
            with sig as (
              select coalesce(s.geo->>'region_code', c.region_code) as region_code, count(*) as total,
                     count(*) filter (where s.sentiment = 'negative') as negative
              from signals s left join clients c on c.id = s.client_id
              where s.received_sim >= %s {run_sql} group by 1
            ), cop as (
              select b.region_code, count(distinct a.id) as sessions,
                     count(tr.id) filter (where tr.status = 'confirmed') as triggers,
                     count(distinct al.id) filter (where al.kind in ('threshold','immediate')) as alerts
              from audio_sessions a join employees e on e.id = a.employee_id join branches b on b.id = e.branch_id
              left join compliance_triggers tr on tr.session_id = a.id left join compliance_alerts al on al.session_id = a.id
              group by 1
            ), inc as (
              select region_code, count(*) as critical_incidents from incidents
              where criticality = 'high' and status not in ('closed','rejected','resolved','duplicate') and region_code is not null and created_sim >= %s
              {"and run_id = %s" if rid is not None else ""} group by 1
            )
            select r.code as region_code, coalesce(sig.total, 0)::int as signals_total, coalesce(sig.negative, 0)::int as negative,
                   case when coalesce(cop.sessions, 0) > 0 then least(1, (cop.triggers::float / 3 + cop.alerts) / cop.sessions) else 0 end as copilot_index,
                   (coalesce(inc.critical_incidents, 0) + coalesce(cop.alerts, 0))::int as critical_count
            from regions r left join sig on sig.region_code = r.code left join cop on cop.region_code = r.code left join inc on inc.region_code = r.code
            """,
            (since, *run_args, since, *run_args),
        )
        no_geo = await fetch_one(
            conn,
            f"select count(*) as n from signals s left join clients c on c.id = s.client_id where s.received_sim >= %s and coalesce(s.geo->>'region_code', c.region_code) is null {run_sql}",
            (since, *run_args),
        )
    w, yellow, red = float(t["copilot_weight"]), float(t["yellow"]), float(t["red"])
    crit_red = int(t["critical_red"])
    neg_max = max((int(r["negative"]) for r in rows), default=0) or 1
    items = []
    computed_at = dt.datetime.now(dt.UTC)
    for r in rows:
        negativity = int(r["negative"]) / neg_max
        idx = min(1.0, negativity + w * r["copilot_index"])
        zone = "red" if r["critical_count"] >= crit_red or idx >= red else "yellow" if idx >= yellow else "green"
        if r["signals_total"] == 0 and r["critical_count"] == 0:
            zone = "green"
        items.append(
            {
                "region_code": r["region_code"],
                "zone": zone,
                "zone_index": round(idx, 3),
                "negativity_index": round(negativity, 3),
                "copilot_index": round(r["copilot_index"], 3),
                "critical_count": r["critical_count"],
                "signals_total": r["signals_total"],
                "computed_at": computed_at,
            }
        )
    return JSONResponse(
        jsonable_encoder(
            {
                "thresholds": {
                    "yellow": yellow,
                    "red": red,
                    "copilot_weight": w,
                    "window_sim_hours": int(t["window_sim_hours"]),
                    "critical_red": crit_red,
                },
                "no_geo_count": int((no_geo or {}).get("n") or 0),
                "items": items,
            }
        )
    )
