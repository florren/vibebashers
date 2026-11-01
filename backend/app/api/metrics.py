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

from app.analytics.dashboard import dashboard
from app.analytics.dashboard import fact as _fact
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.economics import dcltv

router = APIRouter(tags=["metrics"])

OPEN = list(dcltv.OPEN_STATUSES)


@router.get("/api/metrics/dashboard", summary="KPI рабочего места (ТЗ 14.1) — по умолчанию в рамках текущего запуска")
async def get_metrics_dashboard(
    window: str = Query("run", description="run | 24h | 7d | all"), run_id: str | None = Query(None)
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, "all" if window == "all" else run_id)
        out = await dashboard(conn, rid=rid, window=window)
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


@router.get("/api/metrics/cx-index", summary="[ПРОТО] Демонстрационный индекс CX")
async def get_metrics_cx_index(run_id: str | None = Query(None)) -> Any:
    from app.errors import NotImplementedYet

    raise NotImplementedYet("T-256")


@router.get("/api/metrics/economics/preview", summary="Калькулятор потерь без записи в БД")
async def get_economics_preview(
    affected: int = Query(12, ge=0, le=100000000),
    product: str | None = None,
    system: str | None = None,
    segment: str | None = None,
    detractor_share: float = Query(0.1, ge=0, le=1, allow_inf_nan=False),
    no_return_share: float = Query(0.5, ge=0, le=1, allow_inf_nan=False),
) -> Any:
    async with db() as conn:
        cfg = await dcltv.load_settings(conn)
    rate = dcltv.pick_rate(
        cfg["rates"],
        product=product,
        channel=None,
        system=system,
        segment=segment,
        fallback_code=cfg["settings"].get("fallback_rate_code"),
    )
    premium = (
        next((float(r["rate_rub"]) for r in cfg["rates"] if r["code"] == "premium_service"), 91.53)
        if segment in dcltv.PREMIUM_SEGMENTS
        else 0.0
    )
    # compute нормирует реальный инцидент минимум к одному клиенту; калькулятор допускает ноль.
    result = dcltv.compute(
        affected=affected,
        detractor_share=detractor_share if affected else 0,
        no_return_share=no_return_share,
        rate=rate,
        premium_addon=premium,
        retention_factor=0,
        outcome_class="open",
    )
    if affected == 0:
        result["affected_count"] = 0
        result["formula_ru"] = "0 × " + result["formula_ru"].split(" × ", 1)[1]
    return result
