"""Роутер тега `clients` (OpenAPI 1.4.0). Поиск реализован (нужен режиму жюри), «Клиент 360» — карточка T-091."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.common import db, fetch_all, fetch_one

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


def _mask_contacts(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(raw or {})
    for key in ("phone", "email"):
        if out.get(key):
            out[key] = "***"
    return out


@router.get(
    "/api/clients/{id}/360",
    summary="Клиент 360 — профиль, продукты, операции, сигналы, инциденты, состояние и стиль коммуникации",
)
async def get_clients_id_360(id: int, ops_hours: int = Query(default=72, ge=1, le=720)) -> Any:  # noqa: A002
    async with db() as conn:
        client = await fetch_one(
            conn,
            "select c.id, c.public_id, c.display_name, c.segment_code, c.region_code, ct.name_ru as city_name, "
            "c.churn_risk, c.is_active, c.clv_estimate_rub, c.contacts, c.psychotype_code, "
            "p.name_ru as psychotype_name_ru, p.name_en as psychotype_name_en "
            "from clients c left join cities ct on ct.id = c.city_id "
            "left join psychotypes p on p.code = c.psychotype_code where c.id = %s",
            (id,),
        )
        if client is None:
            raise HTTPException(status_code=404, detail="клиент не найден")
        products = await fetch_all(
            conn,
            "select product_code, status from client_products where client_id = %s order by id",
            (id,),
        )
        operations = await fetch_all(
            conn,
            "select id, op_type, status, amount_rub from operations where client_id = %s "
            "and started_sim >= now() - make_interval(hours => %s) order by id desc limit 50",
            (id, ops_hours),
        )
        signals = await fetch_all(
            conn,
            "select id, public_id, channel_code, sentiment, status, received_sim from signals where client_id = %s order by id desc limit 20",
            (id,),
        )
        incidents = await fetch_all(
            conn,
            "select id, public_id, title, incident_type, product_code, system_code, team_code, status from incidents where primary_client_id = %s order by id desc limit 20",
            (id,),
        )
        state = await fetch_one(
            conn,
            "select state, since_sim, care_score, hazard from client_states where client_id = %s order by since_sim desc limit 1",
            (id,),
        )
    return {
        "id": client["id"],
        "public_id": client["public_id"],
        "display_name": client["display_name"],
        "segment_code": client["segment_code"],
        "region_code": client["region_code"],
        "city_name": client["city_name"],
        "churn_risk": client["churn_risk"],
        "is_active": client["is_active"],
        "clv_estimate_rub": client["clv_estimate_rub"],
        "contacts": _mask_contacts(client["contacts"]),
        "psychotype": {
            "code": client["psychotype_code"],
            "name_ru": client["psychotype_name_ru"],
            "name_en": client["psychotype_name_en"],
            "communication_hint_ru": None,
        },
        "products": products,
        "operations": operations,
        "signals": signals,
        "incidents": incidents,
        "current_state": state,
        "state_history": [],
        "gifts": [],
    }
