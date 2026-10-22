"""Роутер тега `map` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-088."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["map"])


@router.get("/api/map/heat", summary="Агрегаты по субъектам РФ для тепловой карты")
async def get_map_heat(request: Request) -> Any:
    raise NotImplementedYet("T-088")


@router.get("/api/map/regions/{code}/cities", summary="Drill-down субъект → города")
async def get_map_regions_code_cities(request: Request) -> Any:
    raise NotImplementedYet("T-088")


@router.get(
    "/api/map/zones",
    summary="[ДТЗ FR-5.2] Слой «Зоны»: зелёная/жёлтая/красная по субъектам (v_map_zones) с индексами негатива и сработок copilot",
)
async def get_map_zones(request: Request) -> Any:
    raise NotImplementedYet("T-088")
