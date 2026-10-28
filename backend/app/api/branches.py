"""Справочник ВСП и агрегированная история сети (T-245), без внешних вызовов."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Response

from app.api.common import db, fetch_all

router = APIRouter(tags=["branches"])


@router.get("/api/branches", summary="[ЕТЗ] Справочник ВСП")
async def list_branches(
    response: Response,
    region_code: str | None = None,
    status: Literal["open", "closed"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=32),
) -> Any:
    where = ["true"]
    args: list[Any] = []
    if region_code:
        where.append("b.region_code = %s")
        args.append(region_code)
    if status:
        where.append("b.branch_status = %s")
        args.append(status)
    if cursor:
        where.append("b.code > %s")
        args.append(cursor)
    async with db() as conn:
        rows = await fetch_all(
            conn,
            "select b.id,b.code,b.name_ru,b.region_code,r.okato as region_okato,c.name_ru as city_name,b.desks,"
            "b.branch_type,b.branch_status,b.lat,b.lon,b.address_ru,b.hours_ru,b.opened_sim,b.closed_sim,b.product_line_codes "
            "from branches b join cities c on c.id=b.city_id join regions r on r.code=b.region_code where "
            + " and ".join(where)
            + " order by b.code limit %s",
            [*args, limit + 1],
        )
    response.headers["Cache-Control"] = "private, max-age=86400"
    more = len(rows) > limit
    items = rows[:limit]
    return {"items": items, "next_cursor": items[-1]["code"] if more else None}


@router.get("/api/branches/network", summary="[ЕТЗ] Динамика сети ВСП")
async def branch_network(
    response: Response, region_code: str | None = None, months: int = Query(default=12, ge=1, le=24)
) -> Any:
    where = "and region_code = %s" if region_code else ""
    args: list[Any] = [months - 1]
    if region_code:
        args.append(region_code)
    async with db() as conn:
        rows = await fetch_all(
            conn,
            "select month, sum(open_count)::int as open_count, sum(closed_count)::int as closed_count, "
            "sum(opened_in_month)::int as opened_in_month,sum(closed_in_month)::int as closed_in_month "
            "from branch_network_history where month >= (select max(month) from branch_network_history) "
            "- make_interval(months => %s) " + where + " group by month order by month",
            args,
        )
    response.headers["Cache-Control"] = "private, max-age=86400"
    return {"items": rows, "synthetic": True}
