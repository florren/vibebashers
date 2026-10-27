"""Роутер тега `cabinet` (OpenAPI 1.5.0). Реализация — T-241."""

from __future__ import annotations

from fastapi import APIRouter, Header, Query

from app.errors import NotImplementedYet

router = APIRouter(tags=["cabinet"])


@router.get("/api/cabinet/overview", summary="[ЕТЗ] KPI кабинета менеджера продукта")
def cabinet_overview(
    product_line: str | None = None,
    period: str = "week",
    run_id: str = "current",
    x_cx_role: str | None = Header(default=None, alias="X-Cx-Role"),
    x_cx_product_line: str | None = Header(default=None, alias="X-Cx-Product-Line"),
) -> None:
    raise NotImplementedYet("T-241")


@router.get("/api/cabinet/report", summary="[ЕТЗ] Отчёт по направлению")
def cabinet_report(
    product_line: str = Query(...),
    period: str = "month",
    format: str = "json",
    run_id: str = "current",
    x_cx_role: str | None = Header(default=None, alias="X-Cx-Role"),
    x_cx_product_line: str | None = Header(default=None, alias="X-Cx-Product-Line"),
) -> None:
    raise NotImplementedYet("T-241")


@router.get("/api/roles", summary="[ЕТЗ] Пресеты ролей кабинета")
def list_roles() -> None:
    raise NotImplementedYet("T-241")
