"""Роутер тега `clients` (OpenAPI 1.4.0). Поиск реализован (нужен режиму жюри), «Клиент 360» — карточка T-091."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.api.common import db, fetch_all
from app.errors import NotImplementedYet

router = APIRouter(tags=["clients"])


@router.get("/api/clients", summary="Поиск клиента (для жюри-режима и фильтров)")
async def get_clients(
    request: Request,
    q: str | None = None,
    segment: str | None = None,
    region_code: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    if q:
        where.append("(c.display_name ilike %s or c.public_id ilike %s or ct.name_ru ilike %s)")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if segment:
        where.append("c.segment_code = %s")
        args.append(segment)
    if region_code:
        where.append("c.region_code = %s")
        args.append(region_code)
    args.append(limit)
    async with db() as conn:
        return await fetch_all(
            conn,
            "select c.id, c.public_id, c.display_name, c.segment_code, c.region_code, ct.name_ru as city_name, c.churn_risk, c.is_active "
            f"from clients c left join cities ct on ct.id = c.city_id where {' and '.join(where)} order by c.is_active desc, c.id limit %s",  # noqa: S608
            args,
        )


@router.get(
    "/api/clients/{id}/360",
    summary="Клиент 360 — профиль, продукты, операции, сигналы, инциденты, состояние и стиль коммуникации",
)
async def get_clients_id_360(request: Request) -> Any:
    raise NotImplementedYet("T-091")
