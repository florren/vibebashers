"""T-241: кабинет и пресеты, read-only транзакция с единым scope."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from app.analytics.cabinet import overview
from app.analytics.cabinet_scope import ROLES, actor_role, resolve_scope, validate_run
from app.analytics.cabinet_signals import signals
from app.errors import NotImplementedYet
from app.trace.store import read_db

router = APIRouter(tags=["cabinet"])
Period = Literal["day", "week", "month", "quarter"]


@router.get("/api/cabinet/overview", summary="[ЕТЗ] KPI кабинета менеджера продукта")
async def cabinet_overview(
    request: Request,
    product_line: str | None = Query(None, max_length=80),
    period: Period = "week",
    run_id: str = Query("current", max_length=32),
) -> Any:
    validate_run(run_id)
    actor_role(request)
    async with read_db() as conn:
        scope = await resolve_scope(conn, request, product_line, period, run_id)
        return await overview(conn, scope)


@router.get("/api/cabinet/signals", summary="[ЕТЗ] Сигналы кабинета с тем же scope")
async def cabinet_signals(
    request: Request,
    product_line: str | None = Query(None, max_length=80),
    period: Period = "week",
    run_id: str = Query("current", max_length=32),
    region: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=40),
    channel: str | None = Query(None, max_length=40),
    red_words: bool | None = None,
    sort: Literal["date", "level", "region"] = "date",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
) -> Any:
    validate_run(run_id)
    actor_role(request)
    async with read_db() as conn:
        scope = await resolve_scope(conn, request, product_line, period, run_id)
        return await signals(
            conn,
            scope,
            region=region,
            status=status,
            channel=channel,
            red_words=red_words,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )


@router.get("/api/cabinet/report", summary="[ЕТЗ] Отчёт по направлению (T-244)")
async def cabinet_report(
    request: Request,
    product_line: str = Query(..., max_length=80),
    period: Period = "month",
    format: Literal["json", "xlsx"] = "json",
    run_id: str = Query("current", max_length=32),
) -> None:
    validate_run(run_id)
    actor_role(request)
    async with read_db() as conn:
        await resolve_scope(conn, request, product_line, period, run_id)
    raise NotImplementedYet("T-244")


@router.get("/api/roles", summary="[ЕТЗ] Пресеты представления, не авторизация")
async def list_roles() -> Any:
    return {
        "default_role": "cx_lead",
        "items": [
            {
                "code": code,
                "name_ru": names[0],
                "name_en": names[1],
                "scope": "one" if code == "product_manager" else "configured" if code == "product_head" else "all",
                "default_red_words": code == "compliance_officer",
            }
            for code, names in ROLES.items()
        ],
    }
